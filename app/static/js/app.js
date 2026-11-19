/* Vastra Mills ERP: small effects layer. Pages work without it; it only adds motion.
   1 scroll reveal  2 counting numbers  3 growing chart bars and progress bars
   4 parallax photos  5 cursor light + 3D tilt on cards  6 button ripple
   7 background switcher  8 Home page carousel buttons */
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* 1 · reveal cards and headings as they scroll into view */
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in");
    if (e.target.dataset.count !== undefined) countUp(e.target);
    io.unobserve(e.target);
  }), { threshold: 0.12 });
  $$(".card, .tile, .story, .mod-card, .ev, .h-xl, .head .lede, .reveal").forEach((el, i) => {
    el.classList.add("rv");
    el.style.setProperty("--d", `${(i % 4) * 70}ms`);
    io.observe(el);
  });

  /* 2 · numbers count up from zero: ₹6.2 L, 28, 1,760 units, 92% */
  const numberEls = $$(".tile .v, .glass .v, .chip .v, .stat-band .v, [data-count]");
  numberEls.forEach((el) => {
    if (el.children.length) return;                 // only plain text values
    const m = el.textContent.match(/^(\D*?)(\d[\d,]*\.?\d*)(.*)$/s);
    if (!m) return;
    el.dataset.count = "";
    Object.assign(el.dataset, { pre: m[1], num: m[2].replace(/,/g, ""), post: m[3],
      dec: (m[2].split(".")[1] || "").length, commas: m[2].includes(",") ? "1" : "" });
    if (!reduce) el.textContent = m[1] + (0).toFixed(+el.dataset.dec) + m[3];
    io.observe(el);
  });
  function countUp(el) {
    const end = parseFloat(el.dataset.num), dec = +el.dataset.dec, t0 = performance.now(), dur = 1400;
    const fmt = (v) => el.dataset.commas ? v.toLocaleString("en-IN", { minimumFractionDigits: dec, maximumFractionDigits: dec }) : v.toFixed(dec);
    if (reduce) { el.textContent = el.dataset.pre + fmt(end) + el.dataset.post; return; }
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = el.dataset.pre + fmt(end * eased) + el.dataset.post;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* 3 · chart bars grow one after another; progress bars fill */
  const grow = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); grow.unobserve(e.target); }
  }), { threshold: 0.25 });
  $$(".chart-plot").forEach((plot) => {
    $$(".stackc", plot).forEach((s, i) => s.style.setProperty("--d", `${i * 55}ms`));
    grow.observe(plot);
  });
  $$(".bar").forEach((b) => grow.observe(b));

  /* 4 · header photos drift slower than the page (parallax) */
  const para = $$(".band img, .hero > img");
  if (para.length && !reduce) {
    let ticking = false;
    const move = () => {
      para.forEach((img) => {
        const r = img.parentElement.getBoundingClientRect();
        if (r.bottom < 0 || r.top > innerHeight) return;
        img.style.setProperty("--py", `${(r.top * -0.18).toFixed(1)}px`);
      });
      ticking = false;
    };
    addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(move); } }, { passive: true });
    move();
  }

  /* 5 · a soft light follows the mouse; small cards tilt in 3D */
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  if (fine && !reduce) {
    $$(".story, .tile, .mod-card").forEach((card) => {
      const tilt = card.matches(".story, .mod-card, .tile");
      card.addEventListener("mousemove", (ev) => {
        const r = card.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
        card.style.setProperty("--mx", `${x * 100}%`);
        card.style.setProperty("--my", `${y * 100}%`);
        if (tilt) card.style.transform =
          `perspective(900px) rotateX(${((0.5 - y) * 7).toFixed(2)}deg) rotateY(${((x - 0.5) * 9).toFixed(2)}deg) translateY(-4px)`;
      });
      card.addEventListener("mouseleave", () => { card.style.transform = ""; });
    });
  }

  /* 6 · ripple where a button is clicked */
  document.addEventListener("pointerdown", (ev) => {
    const btn = ev.target.closest(".btn");
    if (!btn || reduce) return;
    const r = btn.getBoundingClientRect(), size = Math.max(r.width, r.height);
    const dot = document.createElement("span");
    dot.className = "ripple";
    Object.assign(dot.style, { width: `${size}px`, height: `${size}px`, left: `${ev.clientX - r.left - size / 2}px`, top: `${ev.clientY - r.top - size / 2}px` });
    btn.appendChild(dot);
    setTimeout(() => dot.remove(), 650);
  });

  /* 7 · background switcher (remembered in this browser only) */
  const current = document.documentElement.dataset.bg || "glow";
  $$(".bgmenu button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.bg === current));
    b.addEventListener("click", () => {
      document.documentElement.dataset.bg = b.dataset.bg;
      try { localStorage.setItem("vastra-bg", b.dataset.bg); } catch (e) { /* private window: fine */ }
      $$(".bgmenu button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      b.closest("details").open = false;
    });
  });
  document.addEventListener("click", (ev) => {
    $$("details.bgpick[open]").forEach((d) => { if (!d.contains(ev.target)) d.open = false; });
  });

  /* 8 · carousel arrows on the Home page */
  $$("[data-carousel]").forEach((btn) => btn.addEventListener("click", () => {
    const track = document.getElementById(btn.dataset.carousel);
    track.scrollBy({ left: (btn.classList.contains("prev") ? -1 : 1) * track.clientWidth * 0.8, behavior: reduce ? "auto" : "smooth" });
  }));
})();
