/* DEIXIS recorded demo: replays /api responses from api/manifest.json. Loaded before the app bundle. */
(function () {
  'use strict'
  try { localStorage.setItem('deixis-ui-language', 'en') } catch (e) { /* storage blocked */ }
  var HOME = '#/research/res_sxteRYtN7okYNvNDyCA7'
  var script = document.currentScript
  var BASE = new URL('.', script ? script.src : location.href).href
  var MSG = 'This is a recorded demo. Download DEIXIS to run it.'
  var NOT_HERE = 'Not in this demo'
  var origFetch = window.fetch.bind(window)

  function post(m) { try { parent.postMessage(m, '*') } catch (e) { /* standalone */ } }
  try { if (!localStorage.getItem('deixis-theme')) localStorage.setItem('deixis-theme', 'dark') } catch (e) { /* ignore */ }
  try { if (!location.hash || location.hash === '#' || location.hash === '#/') history.replaceState(null, '', location.pathname + location.search + HOME) } catch (e) { /* ignore */ }
  window.addEventListener('hashchange', function () { post({ type: 'deixis-demo', action: 'nav', hash: location.hash }) })
  post({ type: 'deixis-demo', action: 'nav', hash: location.hash })

  // The manifest loads synchronously so the app never starts without it.
  var manifest = { entries: {} }
  try {
    var x = new XMLHttpRequest()
    x.open('GET', BASE + 'api/manifest.json', false)
    x.send()
    manifest = JSON.parse(x.responseText)
  } catch (e) { /* every GET then answers "Not in this demo" */ }
  var VOLATILE = /^(after|ts|t|_|nonce|since|cursor|v|rev)$/i
  function normalize(path) {
    var i = path.indexOf('?')
    if (i < 0) return path
    var pairs = path.slice(i + 1).split('&').filter(function (p) { return p && !VOLATILE.test(p.split('=')[0]) }).sort()
    return path.slice(0, i) + (pairs.length ? '?' + pairs.join('&') : '')
  }
  var entries = manifest.entries || {}
  var normalized = {}
  Object.keys(entries).forEach(function (k) { var n = normalize(k); if (!(n in normalized)) normalized[n] = k })
  function lookup(path) {
    if (entries[path]) return entries[path]
    var n = normalize(path)
    if (normalized[n]) return entries[normalized[n]]
    var bare = path.split('?')[0]
    if (!/\?/.test(path) && normalized[bare]) return entries[normalized[bare]]
    return null
  }
  window.__demoMisses = []

  function apiPath(input) {
    try {
      var u = new URL(typeof input === 'string' ? input : input.url, location.href)
      if (u.origin !== location.origin || u.pathname.indexOf('/api/') !== 0) {
        return null
      }
      return u.pathname + u.search
    } catch (e) { return null }
  }
  function json(status, body) { return new Response(JSON.stringify(body), { status: status, headers: { 'content-type': 'application/json' } }) }
  var bodies = {}
  function searchFallback(path) {
    var q = (new URL(path, location.href).searchParams.get('q') || '').toLowerCase()
    var keys = Object.keys(entries).filter(function (k) { return k.indexOf('/api/search?') === 0 })
    return Promise.all(keys.map(function (k) { return replay(k).then(function (r) { return r.json() }).catch(function () { return null }) })).then(function (all) {
      var out = { researches: [], sources: [] }, seenR = {}, seenS = {}
      all.forEach(function (d) {
        if (!d) return
        ;(d.researches || []).forEach(function (r) { if (!seenR[r.id] && (r.title + ' ' + r.question).toLowerCase().indexOf(q) >= 0) { seenR[r.id] = 1; out.researches.push(r) } })
        ;(d.sources || []).forEach(function (s) { if (!seenS[s.source_version_id] && s.title.toLowerCase().indexOf(q) >= 0) { seenS[s.source_version_id] = 1; out.sources.push(s) } })
      })
      return json(200, out)
    })
  }
  function replay(path) {
    if (path === '/api/session') return Promise.resolve(json(200, { csrf_token: 'demo' }))
    var e = lookup(path)
    if (!e && /^\/api\/search\?/.test(path)) return searchFallback(path)
    if (!e) {
      window.__demoMisses.push(path)
      return Promise.resolve(json(404, { detail: NOT_HERE }))
    }
    var url = BASE + 'api/' + e.f
    var p = bodies[url] || (bodies[url] = origFetch(url).then(function (r) { return r.ok ? r.arrayBuffer() : null }, function () { return null }))
    // api/fulltext/ may be absent (deployed without the documents): the app then shows its normal "not available" state.
    return p.then(function (buf) { return buf ? new Response(buf.slice(0), { status: e.s, headers: { 'content-type': e.t || 'application/json' } }) : json(404, { detail: NOT_HERE }) })
  }
  function label(method, path) {
    var short = path.split('?')[0].replace(/\/(res|run|ans|rep|tbl|src|ver|pas|ast)_[A-Za-z0-9]+/g, '').replace(/^\/api\//, '')
    return method + ' ' + short
  }
  function unavailable(method, path) {
    post({ type: 'deixis-demo', action: 'unavailable', label: label(method, path) })
    return json(503, { detail: MSG })
  }

  window.fetch = function (input, init) {
    var path = apiPath(input)
    if (path === null) return origFetch(input, init)
    var method = ((init && init.method) || (typeof input !== 'string' && input.method) || 'GET').toUpperCase()
    if (method === 'GET' || method === 'HEAD') {
      var why = lookup(path) ? null : blocked(path)
      if (why) {
        post({ type: 'deixis-demo', action: 'unavailable', label: why })
        return Promise.resolve(json(why === 'PDF' ? 404 : 503, { detail: MSG }))
      }
      return replay(path)
    }
    if (entries[method + ' ' + path]) return replay(method + ' ' + path)
    // Theme, sidebar width and similar preferences: the UI keeps working, nothing is saved.
    if (method === 'PUT' && /^\/api\/(settings\/preferences|ui-preferences)/.test(path)) {
      var sent = {}
      try { sent = JSON.parse((init && init.body) || '{}') } catch (e) { /* ignore */ }
      return replay(path).then(function (r) { return r.json().catch(function () { return {} }) }).then(function (cur) { return json(200, Object.assign({}, cur, sent)) })
    }
    return Promise.resolve(unavailable(method, path))
  }

  // XHR: the app does not use it (pdf.js reads through fetch in its worker); kept so a stray call is answered the same way.
  var RealXHR = window.XMLHttpRequest
  function DemoXHR() {
    var real = new RealXHR(), self = this, m = 'GET', path = null
    this.readyState = 0; this.status = 0; this.responseText = ''; this.response = null; this.responseType = ''
    this.onload = this.onerror = this.onreadystatechange = null
    this.open = function (method, url) { m = method.toUpperCase(); path = apiPath(url); if (path === null) real.open.apply(real, arguments) }
    this.setRequestHeader = function () { if (path === null) real.setRequestHeader.apply(real, arguments) }
    this.getResponseHeader = function () { return path === null ? real.getResponseHeader.apply(real, arguments) : null }
    this.abort = function () { if (path === null) real.abort() }
    this.send = function (body) {
      if (path === null) {
        real.onload = function () { self.status = real.status; self.responseText = real.responseText; self.response = real.response; self.readyState = 4; if (self.onload) self.onload() }
        real.onerror = function () { if (self.onerror) self.onerror() }
        real.responseType = self.responseType
        return real.send(body)
      }
      var done = function (r) { r.arrayBuffer().then(function (buf) {
        self.status = r.status; self.readyState = 4
        self.response = self.responseType === 'arraybuffer' ? buf : new TextDecoder().decode(buf)
        self.responseText = typeof self.response === 'string' ? self.response : ''
        if (self.onreadystatechange) self.onreadystatechange()
        if (self.onload) self.onload()
      }) }
      if (m === 'GET' || m === 'HEAD') replay(path).then(done); else done(unavailable(m, path))
    }
  }
  window.XMLHttpRequest = DemoXHR

  // The live event stream: opens, never emits.
  function DemoEventSource(url) {
    this.url = url; this.readyState = 1; this.onmessage = null; this.onerror = null; this.onopen = null
    var self = this
    setTimeout(function () { if (self.onopen) self.onopen({}) }, 0)
  }
  DemoEventSource.prototype.close = function () { this.readyState = 2 }
  DemoEventSource.prototype.addEventListener = function () {}
  DemoEventSource.prototype.removeEventListener = function () {}
  DemoEventSource.CONNECTING = 0; DemoEventSource.OPEN = 1; DemoEventSource.CLOSED = 2
  window.EventSource = DemoEventSource

  // Owner decision: no PDFs, no full documents, no downloads in the demo. Those requests answer like an unavailable file.
  function blocked(path) {
    var p = path.split('?')[0]
    if (/\/export$/.test(p) || /\/export\?/.test(path) || /\/download/.test(p)) return 'Download'
    if (/\/assets\/[^/]+\/text$/.test(p) || /\/figures?(\/|$)/.test(p) || /\/crop$/.test(p)) return 'Full text'
    if (/\/assets\/[^/]+$/.test(p)) return 'PDF'
    return null
  }
  // The one recorded example PDF is read by pdf.js inside its own worker, where this fetch override does not exist: wrap the
  // worker so its fetch is replayed too. Any other PDF answers 404 and the worker tells this page over a BroadcastChannel.
  var bin = {}
  Object.keys(entries).forEach(function (k) { if (/\.pdf$/.test(entries[k].f)) bin[k] = entries[k].f })
  var channel = null
  try { channel = new BroadcastChannel('deixis-demo'); channel.onmessage = function (e) { post({ type: 'deixis-demo', action: 'unavailable', label: String(e.data || 'PDF') }) } } catch (e) { /* no channel */ }
  var RealWorker = window.Worker
  // Runs inside the worker (serialized with toString): replays the one recorded PDF through fetch and XHR, refuses any other /api file.
  function workerPrelude(MAP, BASE) {
    var bc = null
    try { bc = new BroadcastChannel('deixis-demo') } catch (e) { /* no channel */ }
    function key(u) {
      try { var x = new URL(u); return x.pathname.indexOf('/api/') === 0 ? x.pathname + x.search : null } catch (e) { return null }
    }
    function miss() { if (bc) bc.postMessage('PDF') }
    var realFetch = self.fetch.bind(self)
    self.fetch = function (input, init) {
      var k = key(typeof input === 'string' ? input : input.url)
      if (k === null) return realFetch(input, init)
      var n = MAP[k] || MAP[k.split('?')[0]]
      if (!n) { miss(); return Promise.resolve(new Response('{"detail":"Not in this demo"}', { status: 404 })) }
      return realFetch(BASE + 'api/' + n).then(function (r) {
        if (!r.ok) return new Response('{}', { status: 404 })
        return r.arrayBuffer().then(function (b) { return new Response(b, { status: 200, headers: { 'content-type': 'application/pdf' } }) })
      }, function () { return new Response('{}', { status: 404 }) })
    }
    var RX = self.XMLHttpRequest
    if (!RX) return
    self.XMLHttpRequest = function () {
      var real = new RX(), self2 = this, path = null
      this.readyState = 0; this.status = 0; this.response = null; this.responseType = ''
      this.open = function (m, u) { path = key(u); if (path === null) real.open.apply(real, arguments) }
      this.setRequestHeader = function () { if (path === null) real.setRequestHeader.apply(real, arguments) }
      this.getResponseHeader = function (n) { return path === null ? real.getResponseHeader(n) : (/content-type/i.test(n) ? 'application/pdf' : null) }
      this.overrideMimeType = function () {}
      this.abort = function () { if (path === null) real.abort() }
      this.send = function (body) {
        if (path === null) {
          real.responseType = self2.responseType
          real.onreadystatechange = function () { self2.readyState = real.readyState; self2.status = real.status; self2.response = real.response; if (self2.onreadystatechange) self2.onreadystatechange() }
          real.onprogress = function (e) { if (self2.onprogress) self2.onprogress(e) }
          return real.send(body)
        }
        var n = MAP[path] || MAP[path.split('?')[0]]
        var finish = function (status, buf) {
          self2.readyState = 2; self2.status = status; if (self2.onreadystatechange) self2.onreadystatechange()
          self2.readyState = 4; self2.response = buf; if (self2.onreadystatechange) self2.onreadystatechange()
          if (self2.onload) self2.onload()
        }
        if (!n) { miss(); setTimeout(function () { finish(404, null) }, 0); return }
        realFetch(BASE + 'api/' + n).then(function (r) { return r.ok ? r.arrayBuffer() : null }).then(function (b) { finish(b ? 200 : 404, b) }, function () { finish(404, null) })
      }
    }
  }
  var prelude = '(' + workerPrelude.toString() + ')(' + JSON.stringify(bin) + ',' + JSON.stringify(BASE) + ')'
  var preludeUrl = null
  window.Worker = function (url, opts) {
    var abs = new URL(url, location.href).href
    if (/pdf\.worker/.test(abs)) {
      if (!preludeUrl) preludeUrl = URL.createObjectURL(new Blob([prelude], { type: 'text/javascript' }))
      var wrapper = URL.createObjectURL(new Blob(['import ' + JSON.stringify(preludeUrl) + ';import ' + JSON.stringify(abs) + ';'], { type: 'text/javascript' }))
      return new RealWorker(wrapper, { type: 'module' })
    }
    return new RealWorker(url, opts)
  }
  window.Worker.prototype = RealWorker.prototype
})()
