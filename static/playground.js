/* tryfurqan playground: live furqan-lint across Python, Rust, Go.
 *
 * The page has two orthogonal axes:
 *   - language: python | rust | go      (.tab buttons)
 *   - mode:     check   | diff           (.mode-btn buttons)
 *
 * Single source-of-truth state object. Tab and mode switches re-render
 * the editor pane and the fixture grid; the textareas keep their values
 * across switches so users do not lose typed content when comparing.
 *
 * Endpoints:
 *   POST /playground/check  { language, source }
 *   POST /playground/diff   { language, old_source, new_source }
 *   POST /playground/share  { mode, language, source?, old_source?, new_source? }
 *   GET  /s/{share_id}      -> SharePayload (replayed into the UI)
 *
 * Sandbox cap (matches backend): 100 KiB per source.
 */
(function () {
  'use strict';

  var $ = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) {
    return Array.prototype.slice.call(document.querySelectorAll(sel));
  };

  var MAX_BYTES = 100 * 1024;

  // ---------------------------------------------------------------------
  // Empirically-verified fixtures grounded in real v0.8.5 outputs.
  // Each fixture, when loaded, produces the verdict in `expect` against
  // furqan-lint v0.8.5. The tests/fixture_baseline.py harness asserts
  // this on every CI run.
  // ---------------------------------------------------------------------
  var FIXTURES = {
    python: [
      {
        id: 'py-clean',
        title: 'Clean propagation',
        desc: 'Caller declares the same union the callee returns. Expected: PASS.',
        expect: 'pass',
        source:
          'def get_email(uid: int) -> str | None:\n' +
          '    if uid <= 0:\n' +
          '        return None\n' +
          '    return "user@example.com"\n' +
          '\n' +
          'def send_welcome(uid: int) -> str | None:\n' +
          '    e: str | None = get_email(uid)\n' +
          '    return e\n'
      },
      {
        id: 'py-status-collapse',
        title: 'Status collapse (D11)',
        desc: 'Caller narrows away the None arm the callee declared. Expected: MARAD.',
        expect: 'marad',
        source:
          'def get_email(uid: int) -> str | None:\n' +
          '    if uid <= 0:\n' +
          '        return None\n' +
          '    return "user@example.com"\n' +
          '\n' +
          'def send_welcome(uid: int) -> bool:\n' +
          '    e: str = get_email(uid)\n' +
          '    return True\n'
      },
      {
        id: 'py-parse-error',
        title: 'Broken syntax',
        desc: 'Unclosed parenthesis trips the parser. Expected: PARSE ERROR.',
        expect: 'parse_error',
        source:
          'def f(x: int -> int:\n' +
          '    return x\n'
      },
      {
        id: 'py-no-may-fail',
        title: 'No may-fail callee',
        desc: 'Callee returns a flat type, no union to narrow. Expected: PASS.',
        expect: 'pass',
        source:
          'def double(x: int) -> int:\n' +
          '    return x * 2\n' +
          '\n' +
          'def quad(x: int) -> int:\n' +
          '    return double(double(x))\n'
      }
    ],
    rust: [
      {
        id: 'rs-clean',
        title: 'Honest Result propagation',
        desc: 'Caller propagates the Result via `?`. Expected: PASS.',
        expect: 'pass',
        source:
          'pub struct Config { pub name: String }\n' +
          'pub struct Service;\n' +
          '\n' +
          'pub enum ConfigError { NotFound }\n' +
          '\n' +
          'pub fn fetch_config(path: &str) -> Result<Config, ConfigError> {\n' +
          '    Ok(Config { name: path.to_string() })\n' +
          '}\n' +
          '\n' +
          'pub fn init_service(path: &str) -> Result<Service, ConfigError> {\n' +
          '    let config = fetch_config(path)?;\n' +
          '    let _ = config;\n' +
          '    Ok(Service)\n' +
          '}\n'
      },
      {
        id: 'rs-unwrap-collapse',
        title: 'Unwrap collapse (D11)',
        desc: 'Caller `.unwrap()`s the Err arm away. Expected: MARAD.',
        expect: 'marad',
        source:
          'pub struct Config { pub name: String }\n' +
          'pub struct Service;\n' +
          'impl Service { pub fn new(_c: Config) -> Self { Service } }\n' +
          '\n' +
          'pub enum ConfigError { NotFound }\n' +
          '\n' +
          'pub fn fetch_config(path: &str) -> Result<Config, ConfigError> {\n' +
          '    Ok(Config { name: path.to_string() })\n' +
          '}\n' +
          '\n' +
          'pub fn init_service(path: &str) -> Service {\n' +
          '    let config = fetch_config(path).unwrap();\n' +
          '    Service::new(config)\n' +
          '}\n'
      },
      {
        id: 'rs-parse-error',
        title: 'Broken syntax',
        desc: 'Missing brace, dangling token. Expected: PARSE ERROR.',
        expect: 'parse_error',
        source:
          'pub fn broken(x: i32 -> i32 {\n' +
          '    x\n'
      }
    ],
    go: [
      {
        id: 'go-clean',
        title: 'Honest (T, error) propagation',
        desc: 'Caller returns the same union the callee returned. Expected: PASS.',
        expect: 'pass',
        source:
          'package main\n' +
          '\n' +
          'import (\n' +
          '\t"encoding/json"\n' +
          '\t"os"\n' +
          ')\n' +
          '\n' +
          'type Config struct{ Name string }\n' +
          '\n' +
          'func LoadConfig(path string) (*Config, error) {\n' +
          '\tdata, err := os.ReadFile(path)\n' +
          '\tif err != nil {\n' +
          '\t\treturn nil, err\n' +
          '\t}\n' +
          '\tvar cfg Config\n' +
          '\terr = json.Unmarshal(data, &cfg)\n' +
          '\treturn &cfg, err\n' +
          '}\n' +
          '\n' +
          'func ReadConfig(path string) (*Config, error) {\n' +
          '\tcfg, err := LoadConfig(path)\n' +
          '\tif err != nil {\n' +
          '\t\treturn nil, err\n' +
          '\t}\n' +
          '\treturn cfg, nil\n' +
          '}\n'
      },
      {
        id: 'go-blank-collapse',
        title: 'Blank-identifier collapse (D11)',
        desc: 'Caller drops the error arm with `_`. Expected: MARAD.',
        expect: 'marad',
        source:
          'package main\n' +
          '\n' +
          'import (\n' +
          '\t"encoding/json"\n' +
          '\t"os"\n' +
          ')\n' +
          '\n' +
          'type Config struct{ Name string }\n' +
          'type Server struct{}\n' +
          '\n' +
          'func NewServer(c *Config) *Server { return &Server{} }\n' +
          '\n' +
          'func LoadConfig(path string) (*Config, error) {\n' +
          '\tdata, err := os.ReadFile(path)\n' +
          '\tif err != nil { return nil, err }\n' +
          '\tvar cfg Config\n' +
          '\terr = json.Unmarshal(data, &cfg)\n' +
          '\treturn &cfg, err\n' +
          '}\n' +
          '\n' +
          'func StartServer(path string) *Server {\n' +
          '\tcfg, _ := LoadConfig(path)\n' +
          '\treturn NewServer(cfg)\n' +
          '}\n'
      },
      {
        id: 'go-parse-error',
        title: 'Broken syntax',
        desc: 'Unmatched brace. Expected: PARSE ERROR.',
        expect: 'parse_error',
        source:
          'package main\n' +
          '\n' +
          'func broken( {\n'
      }
    ]
  };

  // Diff fixtures: paired (old, new) per language. The "removed name"
  // example is the canonical additive-only marad shape.
  var DIFF_FIXTURES = {
    python: [
      {
        id: 'py-additive-pass',
        title: 'Additive change',
        desc: 'New version adds `gamma`; nothing removed. Expected: PASS.',
        old:
          'def alpha(x: int) -> int:\n' +
          '    return x\n' +
          '\n' +
          'def beta(x: int) -> int:\n' +
          '    return x + 1\n',
        nu:
          'def alpha(x: int) -> int:\n' +
          '    return x\n' +
          '\n' +
          'def beta(x: int) -> int:\n' +
          '    return x + 1\n' +
          '\n' +
          'def gamma(x: int) -> int:\n' +
          '    return x + 2\n',
        expect: 'pass'
      },
      {
        id: 'py-additive-marad',
        title: 'Removed public name',
        desc: 'New version drops `beta`. Expected: MARAD (additive_only).',
        old:
          'def alpha(x: int) -> int:\n' +
          '    return x\n' +
          '\n' +
          'def beta(x: int) -> int:\n' +
          '    return x + 1\n',
        nu:
          'def alpha(x: int) -> int:\n' +
          '    return x\n',
        expect: 'marad'
      }
    ],
    rust: [
      {
        id: 'rs-additive-pass',
        title: 'Additive change',
        desc: 'New version adds a public function. Expected: PASS.',
        old:
          'pub fn alpha(x: i32) -> i32 { x }\n',
        nu:
          'pub fn alpha(x: i32) -> i32 { x }\n' +
          'pub fn beta(x: i32) -> i32 { x + 1 }\n',
        expect: 'pass'
      },
      {
        id: 'rs-additive-marad',
        title: 'Removed public name',
        desc: 'New version drops `beta`. Expected: MARAD (additive_only).',
        old:
          'pub fn alpha(x: i32) -> i32 { x }\n' +
          'pub fn beta(x: i32) -> i32 { x + 1 }\n',
        nu:
          'pub fn alpha(x: i32) -> i32 { x }\n',
        expect: 'marad'
      }
    ],
    go: [
      {
        id: 'go-additive-pass',
        title: 'Additive change',
        desc: 'New version adds an exported function. Expected: PASS.',
        old:
          'package main\n\nfunc Alpha(x int) int { return x }\n',
        nu:
          'package main\n\nfunc Alpha(x int) int { return x }\n\nfunc Beta(x int) int { return x + 1 }\n',
        expect: 'pass'
      },
      {
        id: 'go-additive-marad',
        title: 'Removed exported name',
        desc: 'New version drops `Beta`. Expected: MARAD (additive_only).',
        old:
          'package main\n\nfunc Alpha(x int) int { return x }\n\nfunc Beta(x int) int { return x + 1 }\n',
        nu:
          'package main\n\nfunc Alpha(x int) int { return x }\n',
        expect: 'marad'
      }
    ]
  };

  var SUFFIX_BY_LANG = { python: '.py', rust: '.rs', go: '.go' };

  // ---------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------
  var state = {
    language: 'python',
    mode: 'check',
    sourceByLang: { python: '', rust: '', go: '' },
    diffByLang: {
      python: { old: '', nu: '' },
      rust: { old: '', nu: '' },
      go: { old: '', nu: '' }
    }
  };

  // ---------------------------------------------------------------------
  // DOM handles
  // ---------------------------------------------------------------------
  var checkPane = $('#check-pane');
  var diffPane = $('#diff-pane');
  var sourceEl = $('#source');
  var oldSourceEl = $('#old-source');
  var newSourceEl = $('#new-source');
  var sourceMetaEl = $('#source-meta');
  var diffMetaEl = $('#diff-meta');
  var checkBtn = $('#check-btn');
  var diffBtn = $('#diff-btn');
  var shareBtn = $('#share-btn');
  var diffShareBtn = $('#diff-share-btn');
  var outputEl = $('#output');
  var fixturesEl = $('#fixtures');
  var folioStatus = $('#folio-status');
  var folioNum = $('#folio-num');
  var modeHint = $('#mode-hint');
  var checkSublabel = $('#check-sublabel');
  var diffSublabelOld = $('#diff-sublabel-old');
  var diffSublabelNew = $('#diff-sublabel-new');
  var shareToast = $('#share-toast');
  var installCmd = $('#install-cmd');

  // ---------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------
  function byteLength(str) {
    return new Blob([str]).size;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function setFolio(status, n) {
    if (status) folioStatus.textContent = status;
    if (n != null) folioNum.textContent = 'Folio ' + n;
  }

  function setBusy(busy) {
    checkBtn.disabled = busy;
    diffBtn.disabled = busy;
    shareBtn.disabled = busy;
    diffShareBtn.disabled = busy;
    if (busy) {
      checkBtn.textContent = 'Checking\u2026';
      diffBtn.textContent = 'Diffing\u2026';
    } else {
      checkBtn.textContent = 'Run check';
      diffBtn.textContent = 'Run diff';
    }
  }

  function updateMeta() {
    if (state.mode === 'check') {
      var n = byteLength(sourceEl.value);
      sourceMetaEl.textContent = n.toLocaleString() + ' bytes \u00b7 100 KiB cap';
      sourceMetaEl.style.color = (n > MAX_BYTES) ? '#B85742' : '';
    } else {
      var n1 = byteLength(oldSourceEl.value);
      var n2 = byteLength(newSourceEl.value);
      diffMetaEl.textContent = n1.toLocaleString() + ' / ' +
        n2.toLocaleString() + ' bytes \u00b7 100 KiB cap each';
      diffMetaEl.style.color =
        (n1 > MAX_BYTES || n2 > MAX_BYTES) ? '#B85742' : '';
    }
  }

  function syncStateFromDOM() {
    state.sourceByLang[state.language] = sourceEl.value;
    state.diffByLang[state.language].old = oldSourceEl.value;
    state.diffByLang[state.language].nu = newSourceEl.value;
  }

  function syncDOMFromState() {
    sourceEl.value = state.sourceByLang[state.language] || '';
    oldSourceEl.value = state.diffByLang[state.language].old || '';
    newSourceEl.value = state.diffByLang[state.language].nu || '';
    var sfx = SUFFIX_BY_LANG[state.language];
    checkSublabel.textContent = sfx;
    diffSublabelOld.textContent = sfx;
    diffSublabelNew.textContent = sfx;
    updateMeta();
  }

  function setLanguage(lang) {
    if (lang === state.language) return;
    syncStateFromDOM();
    state.language = lang;
    $$('.tab').forEach(function (t) {
      var on = (t.getAttribute('data-lang') === lang);
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    syncDOMFromState();
    renderFixtures();
    pushUrl();
  }

  function setMode(mode) {
    if (mode === state.mode) return;
    syncStateFromDOM();
    state.mode = mode;
    $$('.mode-btn').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-mode') === mode);
    });
    if (mode === 'check') {
      checkPane.hidden = false;
      diffPane.hidden = true;
      modeHint.textContent = 'Single-file honesty check.';
    } else {
      checkPane.hidden = true;
      diffPane.hidden = false;
      modeHint.textContent = 'Additive-only public-name diff between two versions.';
    }
    updateMeta();
    renderFixtures();
    pushUrl();
  }

  function pushUrl() {
    // Mirror state into the URL so deep links work and back/forward
    // restore. /playground/{lang}[/diff]
    var path = '/playground/' + state.language;
    if (state.mode === 'diff') path = '/playground/diff';
    if (window.location.pathname !== path) {
      try {
        window.history.replaceState({}, '', path);
      } catch (_e) { /* older browsers */ }
    }
  }

  function readUrlIntoState() {
    var p = window.location.pathname;
    if (p === '/playground/diff') {
      state.mode = 'diff';
    } else if (p === '/playground/python') {
      state.language = 'python';
    } else if (p === '/playground/rust') {
      state.language = 'rust';
    } else if (p === '/playground/go') {
      state.language = 'go';
    }
  }

  // ---------------------------------------------------------------------
  // Fixtures grid
  // ---------------------------------------------------------------------
  function renderFixtures() {
    var arr = (state.mode === 'check')
      ? FIXTURES[state.language]
      : DIFF_FIXTURES[state.language];

    var html = '';
    var marks = ['Exhibit A', 'Exhibit B', 'Exhibit C', 'Exhibit D'];
    arr.forEach(function (fx, i) {
      html +=
        '<button class="fixture" type="button" data-fixture-id="' + escapeHtml(fx.id) + '">' +
          '<div class="fixture-mark">' + escapeHtml(marks[i] || ('Exhibit ' + (i + 1))) + '</div>' +
          '<div class="fixture-title">' + escapeHtml(fx.title) + '</div>' +
          '<div class="fixture-desc">' + escapeHtml(fx.desc) + '</div>' +
        '</button>';
    });
    fixturesEl.innerHTML = html;

    $$('.fixture').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-fixture-id');
        loadFixture(id);
      });
    });
  }

  function loadFixture(id) {
    if (state.mode === 'check') {
      var fx = FIXTURES[state.language].find(function (f) { return f.id === id; });
      if (!fx) return;
      sourceEl.value = fx.source;
      state.sourceByLang[state.language] = fx.source;
      updateMeta();
      runCheck();
    } else {
      var fx2 = DIFF_FIXTURES[state.language].find(function (f) { return f.id === id; });
      if (!fx2) return;
      oldSourceEl.value = fx2.old;
      newSourceEl.value = fx2.nu;
      state.diffByLang[state.language].old = fx2.old;
      state.diffByLang[state.language].nu = fx2.nu;
      updateMeta();
      runDiff();
    }
  }

  // ---------------------------------------------------------------------
  // Verdict rendering
  // ---------------------------------------------------------------------
  function renderPanel(result) {
    var verdict = result.verdict || 'error';
    var label = result.verdict_label || 'INTERNAL ERROR';

    var heading = '';
    var body = '';

    if (verdict === 'pass') {
      heading = (result.mode === 'diff')
        ? 'Additive-only contract holds.'
        : 'No structural violations.';
      body = (result.mode === 'diff')
        ? 'No public names were removed between the two versions.'
        : 'Either the function declares the union honestly, or no callee returns one. The signature does not promise more than the body delivers.';
    } else if (verdict === 'advisory') {
      heading = 'Advisory only.';
      body = 'Informational findings; the source passes the structural rules.';
    } else if (verdict === 'marad') {
      heading = 'At least one structural violation.';
      body = (result.mode === 'diff')
        ? 'A public name present in the previous version is absent in the new version, or another diff-mode invariant fired. The diagnostic below names the lost name and the minimal fix.'
        : 'The signature lies on at least one path. Each marad below names the checker, the producer/consumer pair, and the minimal fix.';
    } else if (verdict === 'parse_error') {
      heading = 'The source could not be parsed.';
      body = 'A tokenizer or parser error fired before any checker ran. Diagnostics include the line and column of the failure.';
    } else {
      heading = 'The check did not complete.';
      body = result.error ? String(result.error) : 'See the output panel for details.';
    }

    var output = '';
    if (result.stderr && result.stderr.trim().length) {
      output += result.stderr.trim();
    }
    if (result.stdout && result.stdout.trim().length) {
      if (output.length) output += '\n\n';
      output += result.stdout.trim();
    }
    if (!output.length && result.error) {
      output = String(result.error);
    }

    var elapsed = (result.elapsed_ms != null) ? (result.elapsed_ms + ' ms') : 'n/a';
    var exitCode = (result.exit_code != null) ? result.exit_code : 'n/a';
    var lang = result.language || state.language;
    var modeTag = (result.mode === 'diff') ? 'diff' : 'check';

    outputEl.innerHTML =
      '<div class="panel ' + verdict + '">' +
        '<div class="verdict-badge verdict-' + verdict + '">' + escapeHtml(label) + '</div>' +
        '<p><strong>' + escapeHtml(heading) + '</strong></p>' +
        '<p style="margin-top:0.4rem;">' + escapeHtml(body) + '</p>' +
        (output ? '<pre class="check-output">' + escapeHtml(output) + '</pre>' : '') +
        '<div class="meta-strip">' +
          '<span><strong>Mode</strong> ' + escapeHtml(modeTag) + '</span>' +
          '<span><strong>Language</strong> ' + escapeHtml(lang) + '</span>' +
          '<span><strong>Exit</strong> ' + escapeHtml(exitCode) + '</span>' +
          '<span><strong>Elapsed</strong> ' + escapeHtml(elapsed) + '</span>' +
        '</div>' +
      '</div>';

    setFolio(label, '02');
    outputEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderError(label, headingTxt, msg) {
    outputEl.innerHTML =
      '<div class="panel error">' +
        '<div class="verdict-badge verdict-error">' + escapeHtml(label) + '</div>' +
        '<p><strong>' + escapeHtml(headingTxt) + '</strong></p>' +
        '<p style="margin-top:0.4rem;">' + escapeHtml(msg) + '</p>' +
      '</div>';
  }

  // ---------------------------------------------------------------------
  // Network actions
  // ---------------------------------------------------------------------
  function runCheck() {
    syncStateFromDOM();
    var source = sourceEl.value;
    if (!source || !source.trim().length) {
      renderError('EMPTY', 'Nothing to check.',
        'Paste a function or load a fixture, then run again.');
      return;
    }
    if (byteLength(source) > MAX_BYTES) {
      renderError('INPUT TOO LARGE',
        'Source exceeds the 100 KiB cap.',
        'Trim the input and run again.');
      return;
    }

    setBusy(true);
    setFolio('Checking', '02');
    fetch('/playground/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: state.language, source: source })
    })
      .then(httpJson)
      .then(function (r) { r.mode = 'check'; renderPanel(r); })
      .catch(function (err) {
        renderError('REQUEST FAILED', 'The check request did not complete.',
          err.message || String(err));
      })
      .finally(function () { setBusy(false); });
  }

  function runDiff() {
    syncStateFromDOM();
    var oldSrc = oldSourceEl.value;
    var newSrc = newSourceEl.value;
    if (!oldSrc.trim().length || !newSrc.trim().length) {
      renderError('EMPTY', 'Both versions are required.',
        'Paste an old and new version, or load a fixture pair.');
      return;
    }
    if (byteLength(oldSrc) > MAX_BYTES || byteLength(newSrc) > MAX_BYTES) {
      renderError('INPUT TOO LARGE', 'Source exceeds the 100 KiB cap.',
        'Trim the inputs and run again.');
      return;
    }

    setBusy(true);
    setFolio('Diffing', '02');
    fetch('/playground/diff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        language: state.language,
        old_source: oldSrc,
        new_source: newSrc
      })
    })
      .then(httpJson)
      .then(function (r) { r.mode = 'diff'; renderPanel(r); })
      .catch(function (err) {
        renderError('REQUEST FAILED', 'The diff request did not complete.',
          err.message || String(err));
      })
      .finally(function () { setBusy(false); });
  }

  function httpJson(r) {
    if (!r.ok) {
      return r.text().then(function (t) {
        throw new Error('HTTP ' + r.status + ': ' + t.slice(0, 240));
      });
    }
    return r.json();
  }

  // ---------------------------------------------------------------------
  // Share
  // ---------------------------------------------------------------------
  function showToast(msg, isError) {
    shareToast.innerHTML = msg;
    shareToast.style.borderColor = isError ? '#B85742' : '';
    shareToast.classList.add('visible');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () {
      shareToast.classList.remove('visible');
    }, 6000);
  }

  function runShare() {
    syncStateFromDOM();
    var payload;
    if (state.mode === 'check') {
      var src = sourceEl.value;
      if (!src.trim().length) {
        showToast('<strong>Nothing to share.</strong> Paste source first.', true);
        return;
      }
      payload = { mode: 'check', language: state.language, source: src };
    } else {
      var o = oldSourceEl.value;
      var n = newSourceEl.value;
      if (!o.trim().length || !n.trim().length) {
        showToast('<strong>Nothing to share.</strong> Both versions required.', true);
        return;
      }
      payload = {
        mode: 'diff', language: state.language,
        old_source: o, new_source: n
      };
    }
    fetch('/playground/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(httpJson)
      .then(function (r) {
        var url = window.location.origin + '/s/' + r.share_id;
        var copied = false;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(function () {
            showToast('<strong>Copied:</strong> ' + escapeHtml(url));
          }, function () {
            showToast('<strong>Share link:</strong> ' + escapeHtml(url));
          });
          copied = true;
        }
        if (!copied) {
          showToast('<strong>Share link:</strong> ' + escapeHtml(url));
        }
      })
      .catch(function (err) {
        showToast('<strong>Share failed.</strong> ' +
          escapeHtml(err.message || String(err)), true);
      });
  }

  function maybeLoadShareFromHash() {
    // Support both /s/{id} (server returned playground.html for SPA-ish
    // entry, but actually the server returns 404 since /s/{id} is a JSON
    // endpoint - so this branch is the explicit `?share=ID` query case
    // for completeness).
    var qs = new URLSearchParams(window.location.search);
    var id = qs.get('share');
    if (!id) return;
    fetch('/s/' + encodeURIComponent(id))
      .then(httpJson)
      .then(function (payload) {
        if (!payload || !payload.mode || !payload.language) return;
        state.language = payload.language;
        state.mode = payload.mode;
        if (payload.mode === 'check') {
          state.sourceByLang[payload.language] = payload.source || '';
        } else {
          state.diffByLang[payload.language].old = payload.old_source || '';
          state.diffByLang[payload.language].nu = payload.new_source || '';
        }
        applyStateToUI();
        showToast('<strong>Loaded shared snapshot.</strong>');
      })
      .catch(function (err) {
        showToast('<strong>Could not load shared snapshot.</strong> ' +
          escapeHtml(err.message || String(err)), true);
      });
  }

  function applyStateToUI() {
    $$('.tab').forEach(function (t) {
      var on = (t.getAttribute('data-lang') === state.language);
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    $$('.mode-btn').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-mode') === state.mode);
    });
    if (state.mode === 'check') {
      checkPane.hidden = false; diffPane.hidden = true;
      modeHint.textContent = 'Single-file honesty check.';
    } else {
      checkPane.hidden = true; diffPane.hidden = false;
      modeHint.textContent = 'Additive-only public-name diff between two versions.';
    }
    syncDOMFromState();
    renderFixtures();
    pushUrl();
  }

  // ---------------------------------------------------------------------
  // Wire-up
  // ---------------------------------------------------------------------
  $$('.tab').forEach(function (t) {
    t.addEventListener('click', function () {
      setLanguage(t.getAttribute('data-lang'));
    });
  });
  $$('.mode-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      setMode(b.getAttribute('data-mode'));
    });
  });
  sourceEl.addEventListener('input', updateMeta);
  oldSourceEl.addEventListener('input', updateMeta);
  newSourceEl.addEventListener('input', updateMeta);
  checkBtn.addEventListener('click', runCheck);
  diffBtn.addEventListener('click', runDiff);
  shareBtn.addEventListener('click', runShare);
  diffShareBtn.addEventListener('click', runShare);

  // Cmd/Ctrl + Enter shortcut from any active editor.
  function bindEnterShortcut(el, fn) {
    el.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        fn();
      }
    });
  }
  bindEnterShortcut(sourceEl, runCheck);
  bindEnterShortcut(oldSourceEl, runDiff);
  bindEnterShortcut(newSourceEl, runDiff);

  // Initial render
  readUrlIntoState();
  applyStateToUI();
  setFolio('Ready', '01');
  maybeLoadShareFromHash();
})();
