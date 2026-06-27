/* Reusable "See Accounts HQ in action" carousel — used by ca-partners.html,
   accountshq.html and see-in-action.html. ONE implementation.

   On any page:  <div data-ahq-carousel></div>
                 <script src="screens.js"></script>     (the slide data)
                 <script src="carousel.js"></script>    (this file)

   It injects its own CSS (with sensible colour fallbacks so it works whatever
   the page's CSS variables are), builds every [data-ahq-carousel] mount from
   window.AHQ_SCREENS, and wires the click-to-zoom lightbox. */
(function () {
  var CSS = '\
  .ahq-car{max-width:1080px;margin:0 auto;position:relative}\
  .ahq-track{border-radius:16px}\
  .ahq-slide{display:none}\
  .ahq-slide.on{display:block;animation:ahqfade .35s ease}\
  @keyframes ahqfade{from{opacity:0}to{opacity:1}}\
  .ahq-shot{position:relative;background:#0F1629;border:1px solid var(--line,#E2E8F0);border-bottom:none;border-radius:16px 16px 0 0;overflow:hidden}\
  .ahq-shot img{display:block;width:100%;height:auto;cursor:zoom-in}\
  .ahq-shot::after{content:"\\1F50D Click to zoom";position:absolute;top:10px;right:10px;background:rgba(15,22,41,.82);color:#fff;font-size:11px;font-weight:600;padding:4px 10px;border-radius:7px;pointer-events:none;letter-spacing:.02em}\
  .ahq-copy{background:#fff;border:1px solid var(--line,#E2E8F0);border-top:none;border-radius:0 0 16px 16px;padding:22px 28px}\
  .ahq-copy h3{font-size:21px;font-weight:800;letter-spacing:-.01em;color:var(--ink,#0F172A);margin:0 0 9px}\
  .ahq-copy p{font-size:15.5px;line-height:1.65;color:var(--ink-mute,#475569);margin:0;max-width:780px}\
  .ahq-nav{position:absolute;top:34%;transform:translateY(-50%);width:46px;height:46px;border-radius:50%;border:1px solid var(--line,#E2E8F0);background:#fff;color:var(--ink,#0F172A);font-size:24px;line-height:1;cursor:pointer;box-shadow:0 8px 22px rgba(2,8,23,.20);z-index:2}\
  .ahq-nav:hover{border-color:#0EA5A5;color:#0EA5A5}\
  .ahq-nav.prev{left:-14px}.ahq-nav.next{right:-14px}\
  .ahq-dots{display:flex;justify-content:center;gap:9px;margin-top:18px;flex-wrap:wrap}\
  .ahq-dots button{width:9px;height:9px;border-radius:50%;border:none;background:#CBD5E1;cursor:pointer;padding:0;transition:all .2s}\
  .ahq-dots button.on{background:#0EA5A5;width:26px;border-radius:5px}\
  .ahq-lb{display:none;position:fixed;inset:0;z-index:9999;background:rgba(6,10,20,.93);overflow:auto;cursor:zoom-out;padding:26px;text-align:center}\
  .ahq-lb.on{display:block}\
  .ahq-lb img{display:inline-block;max-width:none;width:min(1600px,96vw);height:auto;border-radius:10px;box-shadow:0 22px 64px rgba(0,0,0,.55);margin:0 auto}\
  .ahq-lb-x{position:fixed;top:12px;right:24px;color:#fff;font-size:36px;line-height:1;cursor:pointer;font-weight:300}\
  @media(max-width:680px){.ahq-nav{top:30%;width:40px;height:40px}.ahq-nav.prev{left:4px}.ahq-nav.next{right:4px}.ahq-copy{padding:18px 18px}}';

  function injectCSS() {
    if (document.getElementById('ahq-car-css')) return;
    var s = document.createElement('style');
    s.id = 'ahq-car-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function ensureLightbox() {
    var lb = document.getElementById('ahq-lb');
    if (lb) return lb;
    lb = document.createElement('div');
    lb.className = 'ahq-lb';
    lb.id = 'ahq-lb';
    lb.setAttribute('aria-hidden', 'true');
    var x = document.createElement('span');
    x.className = 'ahq-lb-x';
    x.setAttribute('aria-label', 'Close');
    x.textContent = '×';
    var im = document.createElement('img');
    im.alt = 'Accounts HQ screen — enlarged';
    lb.appendChild(x);
    lb.appendChild(im);
    document.body.appendChild(lb);
    function close() { lb.classList.remove('on'); document.body.style.overflow = ''; }
    lb.addEventListener('click', close);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    return lb;
  }

  function build(mount) {
    var data = window.AHQ_SCREENS || [];
    if (!data.length) return;
    var lb = ensureLightbox();

    var car = document.createElement('div'); car.className = 'ahq-car';
    var track = document.createElement('div'); track.className = 'ahq-track';
    var prev = document.createElement('button'); prev.type = 'button'; prev.className = 'ahq-nav prev'; prev.setAttribute('aria-label', 'Previous screen'); prev.textContent = '‹';
    var next = document.createElement('button'); next.type = 'button'; next.className = 'ahq-nav next'; next.setAttribute('aria-label', 'Next screen'); next.textContent = '›';
    var dotsEl = document.createElement('div'); dotsEl.className = 'ahq-dots';
    car.appendChild(track); car.appendChild(prev); car.appendChild(next); car.appendChild(dotsEl);
    mount.innerHTML = '';
    mount.appendChild(car);

    data.forEach(function (s, n) {
      var art = document.createElement('article'); art.className = 'ahq-slide';
      var shot = document.createElement('div'); shot.className = 'ahq-shot';
      var img = document.createElement('img'); img.src = s.img; img.alt = s.alt || ''; shot.appendChild(img);
      var copy = document.createElement('div'); copy.className = 'ahq-copy';
      var h = document.createElement('h3'); h.textContent = s.title || '';
      var p = document.createElement('p'); p.textContent = s.body || '';
      copy.appendChild(h); copy.appendChild(p);
      art.appendChild(shot); art.appendChild(copy); track.appendChild(art);
      var d = document.createElement('button'); d.type = 'button'; d.setAttribute('aria-label', 'Go to screen ' + (n + 1));
      d.addEventListener('click', function () { go(n); });
      dotsEl.appendChild(d);
    });

    var slides = [].slice.call(track.querySelectorAll('.ahq-slide'));
    var dots = [].slice.call(dotsEl.children);
    var i = 0;
    function go(n) {
      i = (n + slides.length) % slides.length;
      slides.forEach(function (s, k) { s.classList.toggle('on', k === i); });
      dots.forEach(function (d, k) { d.classList.toggle('on', k === i); });
    }
    prev.addEventListener('click', function () { go(i - 1); });
    next.addEventListener('click', function () { go(i + 1); });
    go(0);

    track.addEventListener('click', function (e) {
      var im = e.target.closest('.ahq-shot img');
      if (!im) return;
      lb.querySelector('img').src = im.getAttribute('src');
      lb.classList.add('on');
      document.body.style.overflow = 'hidden';
    });
  }

  function init() {
    injectCSS();
    var mounts = document.querySelectorAll('[data-ahq-carousel]');
    for (var i = 0; i < mounts.length; i++) build(mounts[i]);
  }

  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
