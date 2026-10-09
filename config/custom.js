/*
  CYBER://HUB -- client-side extras Homepage's YAML can't express.

  Files search bar: injected into the Files card. Submitting opens
  Everything's own web UI in a new tab; the browser runs on this machine, so
  it uses localhost (the container-only host.docker.internal name won't
  resolve here). The browser asks for the Everything login itself -- no
  credentials live in this file.
*/
(() => {
  const EVERYTHING_WEB = "http://localhost:8089/";
  const CARD = 'li.service[data-name="Files"]';

  function addEverythingSearch() {
    const card = document.querySelector(CARD);
    if (!card || card.querySelector(".everything-search")) return;
    const title = card.querySelector(".service-title");
    if (!title) return;

    const form = document.createElement("form");
    form.className = "everything-search";
    form.setAttribute("role", "search");
    form.innerHTML =
      '<input type="search" name="q" placeholder="Search files…" ' +
      'aria-label="Search files with Everything" autocomplete="off" spellcheck="false">';
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const q = form.q.value.trim();
      if (!q) return;
      window.open(`${EVERYTHING_WEB}?search=${encodeURIComponent(q)}`, "_blank", "noopener");
    });
    // Typing inside the card must not trigger Homepage's type-to-search.
    form.addEventListener("keydown", (event) => event.stopPropagation());
    title.insertAdjacentElement("afterend", form);
  }

  // Homepage renders (and re-renders) cards with React after load.
  new MutationObserver(addEverythingSearch).observe(document.body, { childList: true, subtree: true });
  addEverythingSearch();
})();
