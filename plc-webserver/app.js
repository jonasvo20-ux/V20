// V20 drive control via the S7-1200 web server (user-defined pages / AWP)
var MAX_HZ = 50;
var POLL_MS = 500;

var TAG_START = '"Write_Master_DB".Cmd_Start';
var TAG_STOP = '"Write_Master_DB".Cmd_stop';
var TAG_SETPOINT = '"Write_Master_DB".Setpoint_Freq_Hz';

var demo = false;
var demoState = { running: false, freq: 0, setpoint: 0 };

function $(id) { return document.getElementById(id); }

function isTrue(v) {
  v = String(v).trim().toLowerCase();
  return v === '1' || v === 'true';
}

// data.htm returns "key=value" lines, filled in by the PLC
function parseData(text) {
  var out = {};
  text.split(/\r?\n/).forEach(function (line) {
    var i = line.indexOf('=');
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  return out;
}

function setConn(cls, text) {
  var el = $('conn');
  el.className = 'conn ' + cls;
  el.textContent = text;
}

function render(d) {
  var freq = parseFloat(d.freq) || 0;
  $('freq').textContent = freq.toFixed(1);
  $('freqBar').style.width = Math.min(100, Math.abs(freq) / MAX_HZ * 100) + '%';
  $('lampRun').className = isTrue(d.running) ? 'green' : '';
  $('lampFault').className = isTrue(d.fault) ? 'red' : '';
  $('lampDir').className = 'blue';
  $('dirText').textContent = isTrue(d.forward) ? 'Forward' : 'Reverse';
  $('temp').textContent = d.temp !== undefined ? (parseFloat(d.temp) || 0).toFixed(1) : '--';
  $('spPlc').textContent = d.setpoint !== undefined ? (parseFloat(d.setpoint) || 0).toFixed(1) : '--';
}

function demoData() {
  var target = demoState.running ? demoState.setpoint : 0;
  demoState.freq += (target - demoState.freq) * 0.2;
  return {
    freq: demoState.freq, running: demoState.running ? '1' : '0',
    fault: '0', forward: '1', temp: '31.5', setpoint: demoState.setpoint
  };
}

function poll() {
  if (demo) { render(demoData()); return; }
  fetch('data.htm?t=' + Date.now(), { cache: 'no-store', credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
    .then(function (text) {
      var d = parseData(text);
      // Tags not substituted -> page is not served by the PLC
      if (String(d.freq).indexOf(':=') === 0) { enterDemo(); return; }
      setConn('ok', 'PLC online');
      render(d);
    })
    .catch(function () {
      if (location.protocol === 'file:') enterDemo();
      else setConn('err', 'no connection');
    });
}

function enterDemo() {
  demo = true;
  setConn('demo', 'demo mode (not on PLC)');
}

// Write tags: POST form-encoded to the page that declares the AWP_In_Variables
function writeTags(tags) {
  var body = Object.keys(tags).map(function (k) {
    return encodeURIComponent(k) + '=' + encodeURIComponent(tags[k]);
  }).join('&');

  if (demo) {
    if (tags[TAG_START]) demoState.running = true;
    if (tags[TAG_STOP]) demoState.running = false;
    if (tags[TAG_SETPOINT] !== undefined) demoState.setpoint = parseFloat(tags[TAG_SETPOINT]);
    return Promise.resolve();
  }
  return fetch('index.html', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    credentials: 'same-origin',
    body: body
  }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); });
}

function command(btn, tags, okText) {
  btn.disabled = true;
  writeTags(tags)
    .then(function () { $('msg').textContent = okText; })
    .catch(function (e) { $('msg').textContent = 'Write failed: ' + e.message; })
    .then(function () { btn.disabled = false; });
}

function clampSp(v) {
  v = parseFloat(v);
  if (isNaN(v)) v = 0;
  return Math.max(0, Math.min(MAX_HZ, v));
}

$('spSlider').addEventListener('input', function () { $('spNum').value = this.value; });
$('spNum').addEventListener('input', function () { $('spSlider').value = this.value; });

$('btnStart').addEventListener('click', function () {
  var t = {}; t[TAG_START] = 1;
  command(this, t, 'Start sent');
});
$('btnStop').addEventListener('click', function () {
  var t = {}; t[TAG_STOP] = 1;
  command(this, t, 'Stop sent');
});
$('btnSet').addEventListener('click', function () {
  var sp = clampSp($('spNum').value);
  $('spNum').value = sp; $('spSlider').value = sp;
  var t = {}; t[TAG_SETPOINT] = sp;
  command(this, t, 'Setpoint ' + sp + ' Hz sent');
});

poll();
setInterval(poll, POLL_MS);
