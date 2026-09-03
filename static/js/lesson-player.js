/* Accessible lesson player behavior (PRD 8.12.3.1): resume position and
   playback speed. Progressive enhancement only — the native controls remain
   fully usable without JavaScript. */
(function () {
  "use strict";

  function wirePlayer(figure) {
    var media = figure.querySelector("video, audio");
    if (!media) {
      return;
    }
    var resumeSeconds = parseInt(figure.getAttribute("data-resume-seconds") || "0", 10);
    if (resumeSeconds > 0) {
      media.addEventListener("loadedmetadata", function seek() {
        if (media.duration && resumeSeconds < media.duration) {
          media.currentTime = resumeSeconds;
        }
        media.removeEventListener("loadedmetadata", seek);
      });
    }
    var rate = figure.querySelector("[data-playback-rate]");
    if (rate) {
      rate.addEventListener("change", function () {
        media.playbackRate = parseFloat(rate.value);
      });
    }
  }

  document.querySelectorAll(".lesson-player").forEach(wirePlayer);
})();
