'use strict';

const enter = document.getElementById('enter-wall');
if (window.location.protocol !== 'file:') {
  enter.href = './wall.html';
  enter.firstChild.textContent = '进入素材墙 ';
}

const motion = document.getElementById('motion-toggle');
motion.hidden = false;
motion.addEventListener('click', () => {
  const paused = document.documentElement.dataset.motion !== 'paused';
  document.documentElement.dataset.motion = paused ? 'paused' : 'playing';
  motion.setAttribute('aria-pressed', String(paused));
  motion.textContent = paused ? '恢复动效' : '暂停动效';
});
