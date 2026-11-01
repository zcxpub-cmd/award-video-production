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
  if (!response.ok) throw new Error(result.error || `请求失败 (${response.status})`);
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
  fragment.querySelector('.file-name').textContent = asset.source_label || '尚未提供原件';
  fragment.querySelector('.file-name').title = asset.source_label || '';
  fragment.querySelector('.chapter-name').textContent = asset.chapter_id || '未分章';
  fragment.querySelector('.origin-name').textContent = asset.origin || '来源待确认';
  fragment.querySelector('.purpose').textContent = asset.semantic_reason || '尚未填写用途；请先确认与叙事的关系。';
  const badge = fragment.querySelector('.review-badge'); badge.textContent = labels[status.review_status]; badge.classList.add(status.review_status);
  const chips = fragment.querySelector('.sentence-list');
  (asset.sentence_ids || []).slice(0, 3).forEach(s => chips.append(element('span', s, 'chip')));
  if ((asset.sentence_ids || []).length > 3) chips.append(element('span', `+${asset.sentence_ids.length - 3}`, 'chip'));
  if (!(asset.sentence_ids || []).length) chips.append(element('span', '句子映射待补', 'chip'));
  fragment.querySelector('.card-note').textContent = status.review_note ? `备注 · ${status.review_note}` : '';
  const badges = fragment.querySelector('.card-badges');
  if (asset.local_codex_generated === true) badges.append(element('span', 'AI · 本机 Codex 生成', 'ai'));
  const media = asset.media.preview || asset.media.source;
  if (!media) badges.append(element('span', '媒体待补', 'unavailable'));
  const thumb = asset.media.thumbnail || (media && media.mime.startsWith('image/') ? media : null);
  if (thumb) {
    const img = element('img'); img.src = thumb.url; img.alt = `${asset.asset_id} 素材缩略图`; img.loading = 'lazy';
    img.addEventListener('error', () => { img.remove(); const notice = element('div', '缩略图暂不可预览', 'placeholder'); root.querySelector('.card-media').prepend(notice); });
    fragment.querySelector('.placeholder').replaceWith(img);
  } else {
    fragment.querySelector('.media-type').textContent = !media ? '等待本地素材' : media.mime.startsWith('audio/') ? '音频素材' : media.mime.startsWith('image/') ? '图片素材' : '视频素材';
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
  const number = Number(value); return value !== '' && value != null && Number.isFinite(number) ? `${number}s` : '未指定';
}
function openDetail(id) {
  activeId = id; dirty = false;
  const asset = manifest.assets.find(a => a.asset_id === id), review = reviews.assets[id];
  $('detail-title').textContent = asset.asset_id;
  $('detail-chapter').textContent = `${asset.chapter_id || '未分章'} / ${asset.origin || '来源待确认'}`;
  $('detail-purpose').textContent = asset.semantic_reason || '待补充用途与叙事关系。';
  $('detail-sentences').replaceChildren(...(asset.sentence_ids || []).map(id => element('span', id, 'chip')));
  if (!(asset.sentence_ids || []).length) $('detail-sentences').append(element('span', '尚未映射句子', 'chip'));
  $('detail-issues').replaceChildren(...(asset.issues || []).map(message => element('p', message)));
  $('detail-metadata').replaceChildren();
  meta('原始文件', asset.source_label || '未提供'); meta('预览文件', asset.preview_label); meta('素材来源', asset.origin || '待确认');
  meta('生成标记', asset.local_codex_generated === true ? 'AI · 本机 Codex 生成' : '未标记为本机 Codex 生成');
  meta('预览状态', ({provided: '复用提供的预览文件', generated: '已生成代理，待浏览器实际播放验证', original_candidate: '原件预览候选，待浏览器实际播放验证', failed: '代理生成失败，见错误说明', unavailable: '媒体不可用'})[asset.preview_status]);
  if (asset.preview_status === 'generated') meta('代理声音', asset.proxy_audio === 'mute' ? '静音代理；原件音轨不变' : '原音转为 AAC；不代表听感已验收');
  meta('源内范围', `${timeValue(asset.source_in_s)} → ${timeValue(asset.source_out_s)}（制作建议范围）`);
  meta('分辨率', asset.resolution); meta('版本', asset.source_version); meta('文字策略', asset.text_policy); meta('人物 / 标志', asset.person_or_logo);
  meta('重复组', asset.duplicate_group); meta('授权证据', asset.license_evidence); meta('本地可用', asset.availability); meta('探测状态', asset.probe_status); meta('已观看范围', asset.watched_ranges);
  $('player').replaceChildren(); $('media-info').replaceChildren();
  const source = asset.media.preview || asset.media.source;
  if (source) {
    let player;
    if (source.mime.startsWith('video/')) {player = element('video'); player.controls = true; player.playsInline = true; player.preload = 'metadata'; if (asset.media.thumbnail) player.poster = asset.media.thumbnail.url;}
    else if (source.mime.startsWith('audio/')) {player = element('audio'); player.controls = true; player.preload = 'metadata';}
    else if (source.mime.startsWith('image/')) {player = element('img'); player.alt = `${id} 原图预览`;}
    if (player) {
      player.src = source.url;
      player.addEventListener('error', () => $('detail-issues').append(element('p', '浏览器无法解码此格式，或原件已变化。可下载清单内原件，使用本机播放器复核；可另行提供兼容预览文件。')));
      $('player').append(player);
      if (player.tagName === 'VIDEO' || player.tagName === 'AUDIO') {
        const start = Number(asset.source_in_s);
        if ((!asset.media.preview || asset.preview_preserves_timeline === true) && Number.isFinite(start) && start > 0) player.addEventListener('loadedmetadata', () => { if (start < player.duration) player.currentTime = start; }, {once: true});
      }
    } else $('player').append(element('p', '此格式需使用本机专业播放器预览。', 'no-preview'));
    $('media-info').append(element('div', asset.preview_status === 'generated' ? '正在查看自动生成的 H.264 代理：保留完整时长与视场，最长边适配 1280 × 720，不裁切原件。' : asset.media.preview ? '正在查看提供的预览文件；时间范围仍属于原始素材。' : '正在查看原始素材。建议范围只用于定位，不会裁切或改写原件。'));
    if (asset.media.source) {const link = element('a', '下载原件'); link.href = asset.media.source.url; link.download = asset.source_label || id; $('media-info').append(link);}
    if (asset.media.preview) {const link = element('a', '下载预览'); link.href = asset.media.preview.url; link.download = asset.preview_label || id; $('media-info').append(link);}
  } else $('player').append(element('p', '尚无可读取媒体。请在素材清单补齐本地原件，再构建新的素材墙。', 'no-preview'));
  $('edit-status').value = review.review_status; $('edit-note').value = review.review_note;
  $('save-status').textContent = '当前记录已载入'; $('save-status').className = '';
  $('detail').showModal();
}
function stopPlayer() {
  $('player').querySelectorAll('video,audio').forEach(media => {media.pause(); media.removeAttribute('src'); media.load();});
  $('player').replaceChildren();
}
function closeDetail() {
  if ($('save-review').disabled) return;
  if (dirty && !window.confirm('审核修改尚未保存。关闭并放弃这些修改？')) return;
  $('detail').close();
}
async function saveReview() {
  const assetId = activeId;
  const payload = {asset_id: assetId, review_status: $('edit-status').value, review_note: $('edit-note').value};
  $('save-review').disabled = true; $('edit-status').disabled = true; $('edit-note').disabled = true; $('close-detail').disabled = true; $('save-status').textContent = '正在写入本地…'; $('save-status').className = '';
  try {
    const result = await request('/api/reviews', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Wall-Token': token}, body: JSON.stringify(payload)});
    reviews.assets[assetId] = result.review;
    dirty = false; $('save-status').textContent = '✓ 已保存到本地'; render();
  } catch (error) { $('save-status').textContent = error.message; $('save-status').className = 'error'; }
  finally { $('save-review').disabled = false; $('edit-status').disabled = false; $('edit-note').disabled = false; $('close-detail').disabled = false; }
}
async function init() {
  if (location.protocol === 'file:') throw new Error('请通过本机服务打开素材墙：\npython3 <插件目录>/scripts/material_wall.py serve "<此素材墙目录>" --port 8765\n然后打开 http://127.0.0.1:8765/ 。直接双击 HTML 无法保存审核或提供视频 Range 播放。');
  const results = await Promise.all([request('/api/assets'), request('/api/reviews'), request('/api/session')]);
  [manifest, reviews] = results; token = results[2].csrf_token;
  document.title = `${manifest.title} · 素材墙`; $('wall-title').textContent = manifest.title;
  $('startup').textContent = (manifest.warnings || []).join('\n'); $('startup').hidden = !(manifest.warnings || []).length;
  choiceOptions('chapter', manifest.assets.map(a => a.chapter_id)); choiceOptions('origin', manifest.assets.map(a => a.origin));
  ['search','chapter','origin','review'].forEach(id => $(id).addEventListener(id === 'search' ? 'input' : 'change', render));
  $('clear-filters').addEventListener('click', () => { ['search','chapter','origin','review'].forEach(id => $(id).value = ''); render(); });
  $('close-detail').addEventListener('click', closeDetail);
  $('detail').addEventListener('cancel', event => {event.preventDefault(); closeDetail();});
  $('detail').addEventListener('close', stopPlayer);
  ['edit-status','edit-note'].forEach(id => $(id).addEventListener('input', () => {dirty = true; $('save-status').textContent = '有修改待保存'; $('save-status').className = '';}));
  $('save-review').addEventListener('click', saveReview);
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
  render();
}
init().catch(error => { $('startup').hidden = false; $('startup').classList.add('error'); $('startup').textContent = `素材墙尚未就绪\n${error.message}`; });
