'use strict';

const byId = (id) => document.getElementById(id);
const form = byId('convert-form');
const folder = byId('folder');
const frame = byId('map-frame');
const stage = byId('map-stage');
const map = byId('map-image');
const legend = byId('legend');
const layerButtons = Array.from(document.querySelectorAll('[data-layer]'));
const layerNames = {overlay: 'overlay.png', reference: 'reference.png', raw: 'raw.png', filtered: 'filtered.png'};
const fmtCount = new Intl.NumberFormat('zh-CN');
const fmtDecimal = new Intl.NumberFormat('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtPercent = new Intl.NumberFormat('zh-CN', {style: 'percent', maximumFractionDigits: 1});
let result;
let layer = 'overlay';
let zoom = 1;
let shiftX = 0;
let shiftY = 0;
let drag;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function fileUrl(name) {
  return `/files/${result.job}/${name}`;
}

function status(text, kind = 'success') {
  const node = byId('run-state');
  node.dataset.kind = kind;
  node.textContent = text;
}

function marker(row) {
  const swatch = element('i', undefined, 'swatch');
  swatch.style.setProperty('--class-color', row.color);
  swatch.setAttribute('aria-hidden', 'true');
  return swatch;
}

function updateView() {
  const halfWidth = frame.clientWidth * (zoom - 1) / 2;
  const halfHeight = frame.clientHeight * (zoom - 1) / 2;
  shiftX = Math.min(halfWidth, Math.max(-halfWidth, shiftX));
  shiftY = Math.min(halfHeight, Math.max(-halfHeight, shiftY));
  stage.style.transform = `translate(${shiftX}px, ${shiftY}px) scale(${zoom})`;
  stage.classList.toggle('zoomed', zoom > 1);
  byId('zoom-in').disabled = !result || zoom >= 5;
  byId('zoom-out').disabled = !result || zoom <= 1;
  byId('zoom-reset').disabled = !result || zoom === 1;
}

function showLayer(next) {
  if (!result) return;
  layer = next;
  layerButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.layer === layer)));
  map.src = fileUrl(layerNames[layer]);
  const visibleClasses = result.classes.filter((row) => layer === 'raw' || row.kept > 0);
  legend.hidden = layer === 'reference' || visibleClasses.length === 0;
  legend.replaceChildren(...visibleClasses.map((row) => {
    const label = element('span');
    label.append(marker(row), row.name);
    return label;
  }));
}

function summarize() {
  const chart = byId('chart');
  const table = byId('class-table');
  chart.replaceChildren();
  table.replaceChildren();
  byId('chart-key').hidden = result.classes.length === 0;
  byId('stat-context').textContent = `阈值 ${result.threshold.toLocaleString('zh-CN')} m² · ${result.area_method} · 占比按全部有效前景计算`;
  if (!result.classes.length) {
    chart.append(element('p', '掩膜中没有前景像元。', 'hint'));
    const row = table.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 6;
    cell.textContent = '无前景类别';
    return;
  }
  const maximum = Math.max(...result.classes.map((row) => row.raw_m2));
  for (const row of result.classes) {
    const group = element('div');
    const title = element('div', undefined, 'bar-label');
    title.append(element('span', row.name), element('strong', `${fmtDecimal.format(row.area_m2)} m²`));
    const track = element('div', undefined, 'track');
    track.title = `筛除前 ${fmtDecimal.format(row.raw_m2)} m²，筛除后 ${fmtDecimal.format(row.area_m2)} m²`;
    track.setAttribute('aria-label', track.title);
    track.setAttribute('role', 'img');
    track.style.setProperty('--class-color', row.color);
    for (const area of [row.raw_m2, row.area_m2]) {
      const bar = element('span');
      bar.style.width = `${area * 100 / maximum}%`;
      track.append(bar);
    }
    group.append(title, track);
    chart.append(group);

    const line = table.insertRow();
    const label = element('span', undefined, 'class-name');
    label.append(marker(row), row.name);
    line.insertCell().append(label);
    for (const value of [fmtDecimal.format(row.area_m2), fmtDecimal.format(row.area_mu), fmtPercent.format(row.share),
      fmtCount.format(row.kept), fmtCount.format(row.removed)]) line.insertCell().textContent = value;
  }
}

function display(data) {
  result = data;
  zoom = 1;
  shiftX = 0;
  shiftY = 0;
  stage.hidden = false;
  layer = 'overlay';
  byId('source-badge').textContent = result.demo ? '模拟数据 · 玉米倒伏' : '用户导入数据';
  byId('map-meta').textContent = `${result.reference} · ${fmtCount.format(result.width)} × ${fmtCount.format(result.height)} 像元`;
  byId('map-crs').textContent = result.crs;
  byId('metric-tiles').textContent = fmtCount.format(result.tiles);
  byId('metric-kept').textContent = fmtCount.format(result.kept);
  byId('metric-removed').textContent = fmtCount.format(result.removed);
  byId('metric-area').textContent = fmtDecimal.format(result.total_mu);
  byId('map-position').textContent = '在影像上移动鼠标以查看坐标';
  showLayer(layer);
  updateView();
  summarize();
  const all = byId('download-all');
  all.href = fileUrl('all_outputs.zip');
  all.hidden = false;
  byId('downloads').replaceChildren(...Object.entries(result.downloads).filter(([name]) => name !== 'all_outputs.zip')
    .map(([name, label]) => {
      const link = element('a', undefined, 'file-link');
      link.href = fileUrl(name);
      link.append(element('small', name.split('.').pop().toUpperCase()), label);
      return link;
    }));
}

function mapPosition(event) {
  if (!result) return;
  const box = map.getBoundingClientRect();
  const scale = Math.min(box.width / result.width, box.height / result.height);
  const column = (event.clientX - box.left - (box.width - result.width * scale) / 2) / scale;
  const row = (event.clientY - box.top - (box.height - result.height * scale) / 2) / scale;
  if (column < 0 || column >= result.width || row < 0 || row >= result.height) return;
  const [a, b, c, d, e, f] = result.transform;
  const precision = result.projected ? 2 : 6;
  byId('map-position').textContent = `像元 ${Math.floor(column)}, ${Math.floor(row)} · X ${(a * column + b * row + c).toFixed(precision)} · Y ${(d * column + e * row + f).toFixed(precision)}`;
}

async function readResponse(response) {
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(json.error || `服务请求失败（${response.status}）。`);
  return json;
}

async function requestLocal(url, options) {
  try {
    return await fetch(url, options);
  } catch {
    throw new Error('连接本地服务失败。请重新双击 start.bat，使用它打开的网页，并保持启动窗口开启。');
  }
}

for (const button of layerButtons) button.addEventListener('click', () => showLayer(button.dataset.layer));
byId('zoom-in').addEventListener('click', () => { zoom = Math.min(5, zoom * 1.35); updateView(); });
byId('zoom-out').addEventListener('click', () => { zoom = Math.max(1, zoom / 1.35); updateView(); });
byId('zoom-reset').addEventListener('click', () => { zoom = 1; updateView(); });
stage.addEventListener('pointerdown', (event) => {
  if (zoom === 1 || event.button !== 0) return;
  drag = {x: event.clientX - shiftX, y: event.clientY - shiftY};
  stage.setPointerCapture(event.pointerId);
  stage.classList.add('panning');
});
stage.addEventListener('pointermove', (event) => {
  if (drag) {
    shiftX = event.clientX - drag.x;
    shiftY = event.clientY - drag.y;
    updateView();
  }
  mapPosition(event);
});
stage.addEventListener('lostpointercapture', () => { drag = undefined; stage.classList.remove('panning'); });
window.addEventListener('resize', updateView);

form.addEventListener('change', (event) => {
  if (event.target.name === 'mode') byId('upload-area').hidden = form.elements.mode.value !== 'upload';
});
folder.addEventListener('change', () => {
  const first = folder.files[0];
  byId('selection').textContent = first ? `${first.webkitRelativePath.split('/')[0] || '项目文件夹'} · ${folder.files.length} 个文件`
    : '包含参考图、掩膜及可选 CSV 配置。';
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  if (data.get('mode') === 'upload') {
    if (folder.files.length === 0) { status('请先选择项目文件夹。', 'error'); return; }
    for (const file of folder.files) {
      if (/\.(png|bmp|tiff?)$/i.test(file.name) || /^(tiles|classes)\.csv$/i.test(file.name)) {
        data.append('files', file, file.webkitRelativePath || file.name);
      }
    }
  }
  const button = byId('run-button');
  button.disabled = true;
  status('正在处理数据，即将生成预览与导出文件…', 'loading');
  try {
    const response = await requestLocal('/api/convert', {method: 'POST', body: data});
    display(await readResponse(response));
    status(`转换完成 · 保留 ${result.kept} 个斑块，筛除 ${result.removed} 个。`);
  } catch (error) {
    status(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

updateView();
requestLocal('/api/demo').then(readResponse).then((data) => { if (!result) display(data); })
  .catch((error) => status(error.message, 'error'));
