'use strict';

const enter = document.getElementById('enter-wall');
if (window.location.protocol !== 'file:') {
  enter.href = './wall.html';
  enter.firstChild.textContent = '进入素材墙 ';
}

const key = 'yingxu.community.home-scene-order.v1';
const scenesById = new Map(HOME_SCENES.map(scene => [scene.id, scene]));
let deck = { remaining: [], last: null };

function readDeck() {
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved && scenesById.has(saved.last) && Array.isArray(saved.remaining) &&
        saved.remaining.length < scenesById.size &&
        saved.remaining.every(id => scenesById.has(id) && id !== saved.last) &&
        new Set(saved.remaining).size === saved.remaining.length) {
      return saved;
    }
  } catch {
    // This document can still select a scene when storage is unavailable.
  }
  return deck;
}

function nextScene() {
  const { remaining, last } = readDeck();
  const order = [...remaining];
  if (order.length === 0) {
    order.push(...scenesById.keys());
    for (let i = order.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    if (order[0] === last) {
      const j = 1 + Math.floor(Math.random() * (order.length - 1));
      [order[0], order[j]] = [order[j], order[0]];
    }
  }
  const id = order.shift();
  deck = { remaining: order, last: id };
  try {
    localStorage.setItem(key, JSON.stringify(deck));
  } catch {
    // Keep the current deck in memory until this document is closed.
  }
  return scenesById.get(id);
}

const poster = document.getElementById('scene-poster');
const video = document.getElementById('scene-video');
const label = document.getElementById('scene-name');
const motion = document.getElementById('motion-toggle');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let scene;
let paused = false;
let failed = false;
let frame;

function stopFrame() {
  if (frame !== undefined) cancelAnimationFrame(frame);
  frame = undefined;
}

function paint() {
  const blend = Math.min(video.currentTime / 0.28, (video.duration - video.currentTime) / 0.6);
  const progress = Number.isFinite(blend) ? Math.max(0, Math.min(1, blend)) : 0;
  video.style.opacity = String(progress ** 2 * (3 - 2 * progress));
}

function tick() {
  frame = undefined;
  if (document.hidden || video.paused) return;
  paint();
  frame = requestAnimationFrame(tick);
}

function syncPlayback() {
  video.hidden = paused || reduced.matches || failed;
  if (video.hidden || document.hidden) {
    stopFrame();
    video.pause();
    return;
  }
  if (!video.getAttribute('src')) {
    video.src = './cover/' + scene.id + '.mp4';
  }
  void video.play().catch(() => {
    // The selected poster stays visible if autoplay is blocked.
  });
}

function showScene() {
  stopFrame();
  video.pause();
  video.removeAttribute('src');
  video.load();
  video.style.opacity = '0';
  scene = nextScene();
  failed = false;
  label.textContent = scene.name;
  poster.src = './cover/' + scene.id + '.webp';
  poster.alt = '图序主题画面：' + scene.name;
  poster.hidden = false;
  video.dataset.scene = scene.id;
  syncPlayback();
}

video.muted = true;
video.addEventListener('playing', () => {
  if (scene.fadeLoop) {
    if (frame === undefined) tick();
  } else {
    video.style.opacity = '1';
  }
});
video.addEventListener('pause', stopFrame);
video.addEventListener('waiting', stopFrame);
video.addEventListener('seeking', () => {
  if (scene?.fadeLoop) paint();
});
video.addEventListener('error', () => {
  failed = true;
  syncPlayback();
});
document.addEventListener('visibilitychange', syncPlayback);
window.addEventListener('pageshow', event => {
  if (event.persisted) showScene();
});
reduced.addEventListener('change', syncPlayback);
motion.hidden = false;
motion.addEventListener('click', () => {
  paused = !paused;
  motion.setAttribute('aria-pressed', String(paused));
  motion.textContent = paused ? '恢复动效' : '暂停动效';
  syncPlayback();
});

showScene();
