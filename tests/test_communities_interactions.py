"""Tests for interactions, feeds, reactions, and bilateral blocking (PRD 8.17.2)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from communities.contracts import (
    ContentStatus,
    GroupVisibility,
    ReactionType,
)
from communities.interaction_services import (
    add_comment,
    add_reaction,
    attach_file_to_post,
    block_user_bilaterally,
    delete_post,
    edit_post,
    publish_post,
    unblock_user,
)
from communities.selectors import get_group_feed_for_user
from communities.services import (
    create_community_group,
    join_community_group,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Interação")


@pytest.fixture
def therapist_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_interacao@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def author_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="autor@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def peer_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="colega@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def community_group(clinic_fixture: Clinic, therapist_user: Any) -> Any:
    return create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Compartilhar",
        slug="grupo-compartilhar",
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
        slow_mode_seconds=0,
    )


def test_publish_post_neutralizes_xss_and_scripting(
    clinic_fixture: Clinic,
    community_group: Any,
    author_user: Any,
) -> None:
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=author_user,
    )

    malicious_payload = "Olá pessoal! <script>alert('hack')</script> <b>Tudo bem?</b>"
    post = publish_post(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        author_user=author_user,
        content=malicious_payload,
    )

    assert post.status == ContentStatus.PUBLISHED.value
    assert "<script>" not in post.sanitized_content
    assert "alert" not in post.sanitized_content
    assert "Olá pessoal!" in post.sanitized_content


def test_slow_mode_enforces_interval_between_posts(
    clinic_fixture: Clinic,
    therapist_user: Any,
    author_user: Any,
) -> None:
    slow_group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo com Slow Mode",
        slug="slow-mode-group",
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
        slow_mode_seconds=60,
    )
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=slow_group.id,
        user=author_user,
    )

    publish_post(
        clinic_id=clinic_fixture.id,
        group_id=slow_group.id,
        author_user=author_user,
        content="Primeira mensagem rápida.",
    )

    with pytest.raises(ValueError, match="Slow mode active"):
        publish_post(
            clinic_id=clinic_fixture.id,
            group_id=slow_group.id,
            author_user=author_user,
            content="Segunda mensagem imediata (deve falhar).",
        )


def test_edit_and_delete_post(
    clinic_fixture: Clinic,
    community_group: Any,
    author_user: Any,
) -> None:
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=author_user,
    )

    post = publish_post(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        author_user=author_user,
        content="Texto inicial do post.",
    )

    edited = edit_post(
        clinic_id=clinic_fixture.id,
        post_id=post.id,
        author_user=author_user,
        new_content="Texto corrigido e reflexivo.",
    )
    assert edited.status == ContentStatus.EDITED.value
    assert edited.edit_count == 1
    assert "Texto corrigido" in edited.sanitized_content

    deleted = delete_post(
        clinic_id=clinic_fixture.id,
        post_id=post.id,
        user=author_user,
    )
    assert deleted.status == ContentStatus.DELETED.value


def test_comment_and_empathetic_reactions(
    clinic_fixture: Clinic,
    community_group: Any,
    author_user: Any,
    peer_user: Any,
) -> None:
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=author_user,
    )
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=peer_user,
    )

    post = publish_post(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        author_user=author_user,
        content="Hoje celebro 30 dias sem fumar!",
    )

    comment = add_comment(
        clinic_id=clinic_fixture.id,
        post_id=post.id,
        author_user=peer_user,
        content="Parabéns pela conquista! Conte com o grupo.",
    )
    assert comment.author_id == peer_user.pk

    reaction = add_reaction(
        clinic_id=clinic_fixture.id,
        user=peer_user,
        post_id=post.id,
        reaction_type=ReactionType.SUPPORT.value,
    )
    assert reaction.reaction_type == ReactionType.SUPPORT.value


def test_bilateral_social_blocking_filters_feed_for_both_users(
    clinic_fixture: Clinic,
    community_group: Any,
    author_user: Any,
    peer_user: Any,
) -> None:
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=author_user,
    )
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=peer_user,
    )

    post_by_author = publish_post(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        author_user=author_user,
        content="Postagem visível do autor.",
    )
    post_by_peer = publish_post(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        author_user=peer_user,
        content="Postagem visível do colega.",
    )

    # Initial view: both see both posts
    feed_before = get_group_feed_for_user(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        viewer_user=author_user,
    )
    assert len(feed_before) == 2

    # Author blocks Peer bilaterally
    block_user_bilaterally(
        clinic_id=clinic_fixture.id,
        blocker_user=author_user,
        blocked_user_id=peer_user.pk,
    )

    # Author should no longer see peer's post
    feed_author = get_group_feed_for_user(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        viewer_user=author_user,
    )
    author_post_ids = [item["post"].id for item in feed_author]
    assert post_by_author.id in author_post_ids
    assert post_by_peer.id not in author_post_ids

    # Peer should also NOT see author's post (bilateral isolation!)
    feed_peer = get_group_feed_for_user(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        viewer_user=peer_user,
    )
    peer_post_ids = [item["post"].id for item in feed_peer]
    assert post_by_peer.id in peer_post_ids
    assert post_by_author.id not in peer_post_ids

    # Unblock restores visibility
    unblock_user(
        clinic_id=clinic_fixture.id,
        blocker_user=author_user,
        blocked_user_id=peer_user.pk,
    )
    feed_after_unblock = get_group_feed_for_user(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        viewer_user=author_user,
    )
    assert len(feed_after_unblock) == 2


def test_safe_attachment_validation(
    clinic_fixture: Clinic,
    community_group: Any,
    author_user: Any,
) -> None:
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        user=author_user,
    )

    post = publish_post(
        clinic_id=clinic_fixture.id,
        group_id=community_group.id,
        author_user=author_user,
        content="Post com anexo de comprovante de caminhada.",
    )

    # Valid PNG attachment
    safe_attachment = attach_file_to_post(
        clinic_id=clinic_fixture.id,
        post_id=post.id,
        uploader_user=author_user,
        file_name="grafico_caminhada.png",
        mime_type="image/png",
        file_bytes=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    )
    assert safe_attachment.is_clean is True
    assert safe_attachment.mime_type == "image/png"

    # Reject forbidden MIME type (e.g. executable or raw html)
    with pytest.raises(ValueError, match="MIME type 'text/html' not allowed"):
        attach_file_to_post(
            clinic_id=clinic_fixture.id,
            post_id=post.id,
            uploader_user=author_user,
            file_name="script_malicioso.html",
            mime_type="text/html",
            file_bytes=b"<html><script>alert(1)</script></html>",
        )
