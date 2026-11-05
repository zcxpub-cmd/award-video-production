'use strict';
const $ = id => document.getElementById(id);
const labels = {pending: '待审', approved: '通过', rejected: '弃用'};
let manifest, reviews, token, activeId, dirty = false;
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
async function request(url, options) {
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || trWall("请求失败 ({0})", response.status));
  return result;
}
function choiceOptions(id, values) {
  [...new Set(values.filter(Boolean).map(String))].sort((a,b) => a.localeCompare(b, 'zh')).forEach(value => {
    const option = element('option', value); option.value = value; $(id).append(option);
  });
}
function updateStats() {
  const counts = {pending: 0, approved: 0, rejected: 0};
  manifest.assets.forEach(asset => counts[reviews.assets[asset.asset_id].review_status]++);
  $('total-count').textContent = manifest.assets.length;
  Object.keys(counts).forEach(status => $(status + '-count').textContent = counts[status]);
  const progress = manifest.assets.length ? Math.round(100 * (counts.approved + counts.rejected) / manifest.assets.length) : 0;
  $('progress').value = progress; $('progress-label').textContent = `${progress}%`;
}
function card(asset) {
  const fragment = $('card-template').content.cloneNode(true);
  const root = fragment.querySelector('.card');
  const status = reviews.assets[asset.asset_id];
  root.dataset.assetId = asset.asset_id;
  fragment.querySelector('.asset-name').textContent = asset.asset_id;
  fragment.querySelector('.file-name').textContent = asset.source_label || trWall("尚未提供原件");
  fragment.querySelector('.file-name').title = asset.source_label || '';
  fragment.querySelector('.chapter-name').textContent = asset.chapter_id || trWall("未分章");
  fragment.querySelector('.origin-name').textContent = asset.origin || trWall("来源待确认");
  fragment.querySelector('.purpose').textContent = asset.semantic_reason || trWall("尚未填写用途；请先确认与叙事的关系。");
  const badge = fragment.querySelector('.review-badge'); badge.textContent = trWall(labels[status.review_status]); badge.classList.add(status.review_status);
  const chips = fragment.querySelector('.sentence-list');
  (asset.sentence_ids || []).slice(0, 3).forEach(s => chips.append(element('span', s, 'chip')));
  if ((asset.sentence_ids || []).length > 3) chips.append(element('span', `+${asset.sentence_ids.length - 3}`, 'chip'));
  if (!(asset.sentence_ids || []).length) chips.append(element('span', trWall("句子映射待补"), 'chip'));
  fragment.querySelector('.card-note').textContent = status.review_note ? trWall("备注 · {0}", status.review_note) : '';
  const badges = fragment.querySelector('.card-badges');
  if (asset.local_codex_generated === true) badges.append(element('span', trWall("AI · 本机 Codex 生成"), 'ai'));
  const media = asset.media.preview || asset.media.source;
  if (!media) badges.append(element('span', trWall("媒体待补"), 'unavailable'));
  const thumb = asset.media.thumbnail || (media && media.mime.startsWith('image/') ? media : null);
  if (thumb) {
    const img = element('img'); img.src = thumb.url; img.alt = trWall("{0} 素材缩略图", asset.asset_id); img.loading = 'lazy';
    img.addEventListener('error', () => { img.remove(); const notice = element('div', trWall("缩略图暂不可预览"), 'placeholder'); root.querySelector('.card-media').prepend(notice); });
    fragment.querySelector('.placeholder').replaceWith(img);
  } else {
    fragment.querySelector('.media-type').textContent = !media ? trWall("等待本地素材") : media.mime.startsWith('audio/') ? trWall("音频素材") : media.mime.startsWith('image/') ? trWall("图片素材") : trWall("视频素材");
    fragment.querySelector('.media-symbol').textContent = media && media.mime.startsWith('audio/') ? '♫' : '▷';
  }
  fragment.querySelector('.open-card').addEventListener('click', () => openDetail(asset.asset_id));
  return fragment;
}
function render() {
  const query = $('search').value.trim().toLocaleLowerCase();
  const chapter = $('chapter').value, origin = $('origin').value, status = $('review').value;
  const selected = manifest.assets.filter(asset => {
    const review = reviews.assets[asset.asset_id];
    return (!chapter || String(asset.chapter_id) === chapter) && (!origin || String(asset.origin) === origin) && (!status || review.review_status === status) && (!query || [asset.asset_id, asset.source_label, asset.preview_label, asset.chapter_id, asset.origin, asset.semantic_reason, ...(asset.sentence_ids || []), review.review_note].join(' ').toLocaleLowerCase().includes(query));
  });
  $('wall').replaceChildren(...selected.map(card));
  $('visible-count').textContent = selected.length;
  $('empty').hidden = selected.length > 0;
  updateStats();
}
function meta(label, value) {
  if (value === undefined || value === null || value === '') return;
  $('detail-metadata').append(element('dt', label), element('dd', Array.isArray(value) ? value.join('、') : String(value)));
}
function timeValue(value) {
  const number = Number(value); return value !== '' && value != null && Number.isFinite(number) ? `${number}s` : trWall("未指定");
}
function openDetail(id) {
  activeId = id; dirty = false;
  const asset = manifest.assets.find(a => a.asset_id === id), review = reviews.assets[id];
  $('detail-title').textContent = asset.asset_id;
  $('detail-chapter').textContent = `${asset.chapter_id || trWall("未分章")} / ${asset.origin || trWall("来源待确认")}`;
  $('detail-purpose').textContent = asset.semantic_reason || trWall("待补充用途与叙事关系。");
  $('detail-sentences').replaceChildren(...(asset.sentence_ids || []).map(id => element('span', id, 'chip')));
  if (!(asset.sentence_ids || []).length) $('detail-sentences').append(element('span', trWall("尚未映射句子"), 'chip'));
  $('detail-issues').replaceChildren(...(asset.issues || []).map(message => element('p', message)));
  $('detail-metadata').replaceChildren();
  meta(trWall("原始文件"), asset.source_label || trWall("未提供")); meta(trWall("预览文件"), asset.preview_label); meta(trWall("素材来源"), asset.origin || trWall("待确认"));
  meta(trWall("生成标记"), asset.local_codex_generated === true ? trWall("AI · 本机 Codex 生成") : trWall("未标记为本机 Codex 生成"));
  meta(trWall("预览状态"), ({provided: trWall("复用提供的预览文件"), generated: trWall("已生成代理，待浏览器实际播放验证"), original_candidate: trWall("原件预览候选，待浏览器实际播放验证"), failed: trWall("代理生成失败，见错误说明"), unavailable: trWall("媒体不可用")})[asset.preview_status]);
  if (asset.preview_status === 'generated') meta(trWall("代理声音"), asset.proxy_audio === 'mute' ? trWall("静音代理；原件音轨不变") : trWall("原音转为 AAC；不代表听感已验收"));
  meta(trWall("源内范围"), trWall("{0} → {1}（制作建议范围）", timeValue(asset.source_in_s), timeValue(asset.source_out_s)));
  meta(trWall("分辨率"), asset.resolution); meta(trWall("版本"), asset.source_version); meta(trWall("文字策略"), asset.text_policy); meta(trWall("人物 / 标志"), asset.person_or_logo);
  meta(trWall("重复组"), asset.duplicate_group); meta(trWall("授权证据"), asset.license_evidence); meta(trWall("本地可用"), asset.availability); meta(trWall("探测状态"), asset.probe_status); meta(trWall("已观看范围"), asset.watched_ranges);
  $('player').replaceChildren(); $('media-info').replaceChildren();
  const source = asset.media.preview || asset.media.source;
  if (source) {
    let player;
    if (source.mime.startsWith('video/')) {player = element('video'); player.controls = true; player.playsInline = true; player.preload = 'metadata'; if (asset.media.thumbnail) player.poster = asset.media.thumbnail.url;}
    else if (source.mime.startsWith('audio/')) {player = element('audio'); player.controls = true; player.preload = 'metadata';}
    else if (source.mime.startsWith('image/')) {player = element('img'); player.alt = trWall("{0} 原图预览", id);}
    if (player) {
      player.src = source.url;
      player.addEventListener('error', () => $('detail-issues').append(element('p', trWall("浏览器无法解码此格式，或原件已变化。可下载清单内原件，使用本机播放器复核；可另行提供兼容预览文件。"))));
      $('player').append(player);
      if (player.tagName === 'VIDEO' || player.tagName === 'AUDIO') {
        const start = Number(asset.source_in_s);
        if ((!asset.media.preview || asset.preview_preserves_timeline === true) && Number.isFinite(start) && start > 0) player.addEventListener('loadedmetadata', () => { if (start < player.duration) player.currentTime = start; }, {once: true});
      }
    } else $('player').append(element('p', trWall("此格式需使用本机专业播放器预览。"), 'no-preview'));
    $('media-info').append(element('div', asset.preview_status === 'generated' ? trWall("正在查看自动生成的 H.264 代理：保留完整时长与视场，最长边适配 1280 × 720，不裁切原件。") : asset.media.preview ? trWall("正在查看提供的预览文件；时间范围仍属于原始素材。") : trWall("正在查看原始素材。建议范围只用于定位，不会裁切或改写原件。")));
    if (asset.media.source) {const link = element('a', trWall("下载原件")); link.href = asset.media.source.url; link.download = asset.source_label || id; $('media-info').append(link);}
    if (asset.media.preview) {const link = element('a', trWall("下载预览")); link.href = asset.media.preview.url; link.download = asset.preview_label || id; $('media-info').append(link);}
  } else $('player').append(element('p', trWall("尚无可读取媒体。请在素材清单补齐本地原件，再构建新的素材墙。"), 'no-preview'));
  $('edit-status').value = review.review_status; $('edit-note').value = review.review_note;
  $('save-status').textContent = trWall("当前记录已载入"); $('save-status').className = '';
  $('detail').showModal();
}
function stopPlayer() {
  $('player').querySelectorAll('video,audio').forEach(media => {media.pause(); media.removeAttribute('src'); media.load();});
  $('player').replaceChildren();
}
function closeDetail() {
  if ($('save-review').disabled) return;
  if (dirty && !window.confirm(trWall("审核修改尚未保存。关闭并放弃这些修改？"))) return;
  $('detail').close();
}
async function saveReview() {
  const assetId = activeId;
  const payload = {asset_id: assetId, review_status: $('edit-status').value, review_note: $('edit-note').value};
  $('save-review').disabled = true; $('edit-status').disabled = true; $('edit-note').disabled = true; $('close-detail').disabled = true; $('save-status').textContent = trWall("正在写入本地…"); $('save-status').className = '';
  try {
    const result = await request('/api/reviews', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Wall-Token': token}, body: JSON.stringify(payload)});
    reviews.assets[assetId] = result.review;
    dirty = false; $('save-status').textContent = trWall("✓ 已保存到本地"); render();
  } catch (error) { $('save-status').textContent = error.message; $('save-status').className = 'error'; }
  finally { $('save-review').disabled = false; $('edit-status').disabled = false; $('edit-note').disabled = false; $('close-detail').disabled = false; }
}
async function init() {
  if (location.protocol === 'file:') throw new Error(trWall("请通过本机服务打开素材墙：\npython3 <插件目录>/scripts/material_wall.py serve \"<此素材墙目录>\" --port 8765\n然后打开 http://127.0.0.1:8765/ 。直接双击 HTML 无法保存审核或提供视频 Range 播放。"));
  const results = await Promise.all([request('/api/assets'), request('/api/reviews'), request('/api/session')]);
  [manifest, reviews] = results; token = results[2].csrf_token;
  $('wall-title').textContent = trWall(manifest.title);
  $('current-project').textContent = trWall(manifest.title);
  showWorkspacePage();
  $('startup').textContent = (manifest.warnings || []).join('\n'); $('startup').hidden = !(manifest.warnings || []).length;
  choiceOptions('chapter', manifest.assets.map(a => a.chapter_id)); choiceOptions('origin', manifest.assets.map(a => a.origin));
  ['search','chapter','origin','review'].forEach(id => $(id).addEventListener(id === 'search' ? 'input' : 'change', render));
  $('clear-filters').addEventListener('click', () => { ['search','chapter','origin','review'].forEach(id => $(id).value = ''); render(); });
  $('close-detail').addEventListener('click', closeDetail);
  $('detail').addEventListener('cancel', event => {event.preventDefault(); closeDetail();});
  $('detail').addEventListener('close', stopPlayer);
  ['edit-status','edit-note'].forEach(id => $(id).addEventListener('input', () => {dirty = true; $('save-status').textContent = trWall("有修改待保存"); $('save-status').className = '';}));
  $('save-review').addEventListener('click', saveReview);
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
  render();
}
init().catch(error => { $('startup').hidden = false; $('startup').classList.add('error'); $('startup').textContent = trWall("素材墙尚未就绪") + "\n" + error.message; });

const routes = new Map(Array.from(document.querySelectorAll('[data-route]'), link => [link.dataset.route, link]));
const panels = Array.from(document.querySelectorAll('[data-page]'));
const themeKey = 'yingxu.community.theme';
let toastTimeout;
let theme = 'dark';

function setNavigation(open) {
  document.querySelector('.shell').toggleAttribute('data-nav-open', open);
  $('nav-toggle').setAttribute('aria-expanded', String(open));
}

function showWorkspacePage() {
  const requested = location.hash.slice(1);
  const route = routes.has(requested) ? requested : 'assets';
  const label = routes.get(route).textContent.trim();
  for (const [name, link] of routes) {
    if (name === route) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  for (const panel of panels) panel.hidden = panel.dataset.page !== route;
  $('workspace-page').textContent = label;
  document.title = `${trWall(manifest?.title || "影序")} · ${label}`;
  setNavigation(false);
}

function setTheme(next) {
  theme = next === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  $('theme-toggle').textContent = theme === 'light' ? trWall("暖白") : trWall("暗黑");
  $('theme-toggle').setAttribute('aria-label', trWall("当前主题为{0}，点击切换", $('theme-toggle').textContent));
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
  });
  try { localStorage.setItem(themeKey, theme); } catch {}
}

function notify(message) {
  clearTimeout(toastTimeout);
  const toast = $('workspace-toast');
  toast.textContent = message;
  toast.hidden = false;
  toastTimeout = setTimeout(() => { toast.hidden = true; }, 3800);
}

try { theme = localStorage.getItem(themeKey) || theme; } catch {}
setTheme(theme);
showWorkspacePage();
window.addEventListener('hashchange', () => {
  showWorkspacePage();
  $('workspace-body').scrollIntoView({block: 'start'});
});
$('nav-toggle').addEventListener('click', () => {
  setNavigation($('nav-toggle').getAttribute('aria-expanded') !== 'true');
});
window.addEventListener('keydown', event => {
  if (event.key === 'Escape' && $('nav-toggle').getAttribute('aria-expanded') === 'true') {
    setNavigation(false);
    $('nav-toggle').focus();
  }
});
$('theme-toggle').addEventListener('click', () => setTheme(theme === 'dark' ? 'light' : 'dark'));
document.querySelectorAll('[data-theme-choice]').forEach(button => {
  button.addEventListener('click', () => setTheme(button.dataset.themeChoice));
});
document.querySelectorAll('.copy-command').forEach(button => {
  button.addEventListener('click', async () => {
    const command = button.closest('.workflow-card').querySelector('code');
    try {
      await navigator.clipboard.writeText(command.textContent);
      notify(trWall("已复制命令"));
    } catch {
      const range = document.createRange();
      range.selectNodeContents(command);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      notify(trWall("已选中命令，可以手动复制"));
    }
  });
});

window.addEventListener('yingxu-language-change', () => {
  setTheme(theme);
  showWorkspacePage();
  if (!manifest) return;
  $('wall-title').textContent = trWall(manifest.title);
  $('current-project').textContent = trWall(manifest.title);
  render();
});
