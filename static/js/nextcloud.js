// nextcloud.js — Nextcloud Files explorer with inline open-in-asset support.
//
// Opens a modal file browser over /api/nextcloud/* (added in routes/nextcloud_routes.py).
// Text/code files can be opened in the document editor, PDFs in the PDF viewer, and
// images in the Gallery via /api/nextcloud/open-in-asset.
// Self-contained: it builds its DOM with createElement/textContent so untrusted
// file/folder names from the server can't inject markup, reuses the app's CSS
// variables (--panel/--border/--fg/--accent) and inline monochrome SVG icons,
// and uses no Unicode emoji. Credentials ride the same-origin session cookie.
//
// Public entry point: window.openNextcloudExplorer(accountId, label)

function _ncIcon(name) {
  // Monochrome inline SVGs matching the rest of the UI's icon style.
  const icons = {
    folder: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    file: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    close: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    back: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>',
    edit: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="M15 5l4 4"/></svg>',
    eye: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
    image: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
  };
  return icons[name] || '';
}

function _ncHumanSize(n) {
  if (n === null || n === undefined || isNaN(n)) return '';
  const f = Number(n);
  if (f < 1024) return f + ' B';
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = f / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(1) + ' ' + units[i];
}

function _ncFileUrl(accountId, path) {
  return '/api/nextcloud/file?account=' + encodeURIComponent(accountId) + '&path=' + encodeURIComponent(path);
}

function _ncIsPdf(entry) {
  if ((entry.content_type || '').toLowerCase() === 'application/pdf') return true;
  return (entry.name.split('.').pop() || '').toLowerCase() === 'pdf';
}

function _ncIsImage(entry) {
  if ((entry.content_type || '').toLowerCase().startsWith('image/')) return true;
  return ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].indexOf((entry.name.split('.').pop() || '').toLowerCase()) !== -1;
}

function _ncIsText(entry) {
  var ct = (entry.content_type || '').toLowerCase();
  // Content-type based detection
  if (ct.startsWith('text/')) return true;
  if (['application/json', 'application/xml', 'application/javascript',
       'application/x-yaml', 'application/x-python', 'application/x-shellscript'
      ].indexOf(ct) !== -1) return true;
  // Extension-based detection for common text/code files
  var exts = ['py', 'js', 'ts', 'md', 'txt', 'html', 'css', 'json', 'yaml', 'yml',
              'xml', 'csv', 'sh', 'bash', 'sql', 'rs', 'go', 'java', 'c', 'cpp',
              'rb', 'php', 'toml', 'ini'];
  var ext = (entry.name.split('.').pop() || '').toLowerCase();
  return exts.indexOf(ext) !== -1;
}

// In-app viewer for images. Now renders via the Gallery asset flow.
function _ncOpenViewer(accountId, entry) {
  const url = _ncFileUrl(accountId, entry.path);
  const backdrop = document.createElement('div');
  backdrop.className = 'nc-viewer-backdrop';
  backdrop.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.72);display:flex;align-items:center;justify-content:center;padding:24px;';
  const panel = document.createElement('div');
  panel.style.cssText = 'background:var(--panel,#111);border:1px solid var(--border);border-radius:10px;width:min(960px,100%);height:min(88vh,820px);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.5);';
  const header = document.createElement('div');
  header.style.cssText = 'display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border);';
  const title = document.createElement('div');
  title.style.cssText = 'font-weight:600;font-size:13px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--accent,var(--red));display:flex;align-items:center;gap:6px;';
  title.innerHTML = _ncIcon('file');
  const nameSpan = document.createElement('span');
  nameSpan.textContent = entry.name;
  title.appendChild(nameSpan);
  const dl = document.createElement('a');
  dl.href = url; dl.download = entry.name; dl.target = '_blank'; dl.title = 'Download';
  dl.style.cssText = 'color:var(--fg);opacity:0.7;display:inline-flex;padding:4px;';
  dl.innerHTML = _ncIcon('download');
  const closeBtn = document.createElement('button');
  closeBtn.title = 'Close (Esc)';
  closeBtn.style.cssText = 'background:none;border:none;color:var(--fg);cursor:pointer;padding:4px;display:inline-flex;opacity:0.7;';
  closeBtn.innerHTML = _ncIcon('close');
  closeBtn.onclick = () => backdrop.remove();
  header.appendChild(title); header.appendChild(dl); header.appendChild(closeBtn);
  const body = document.createElement('div');
  body.style.cssText = 'flex:1;overflow:auto;background:var(--bg,#000);';
  panel.appendChild(header); panel.appendChild(body);
  backdrop.appendChild(panel);
  document.body.appendChild(backdrop);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) backdrop.remove(); });
  const onKey = (e) => { if (e.key === 'Escape') { backdrop.remove(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);

  if (_ncIsImage(entry)) {
    const img = document.createElement('img');
    img.src = url; img.alt = entry.name;
    img.style.cssText = 'max-width:100%;max-height:100%;display:block;margin:auto;padding:8px;';
    body.appendChild(img);
  } else {
    // Non-image files open in a new tab.
    backdrop.remove();
    window.open(url, '_blank');
  }
}

// Open a Nextcloud file in the appropriate Odysseus asset (editor/viewer/gallery).
function _ncOpenInAsset(accountId, entry) {
  var sessionId = '';
  try {
    // Try to read the current session from the session module (dynamic import).
    if (window.sessionModule && window.sessionModule.getCurrentSessionId) {
      sessionId = window.sessionModule.getCurrentSessionId() || '';
    }
  } catch (_) {}

  return fetch('/api/nextcloud/open-in-asset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({
      account_id: accountId,
      path: entry.path,
      session_id: sessionId || undefined
    })
  })
  .then(function(r) {
    if (!r.ok) {
      return r.json().then(function(d) {
        throw new Error(d.detail || d.error || ('HTTP ' + r.status));
      });
    }
    return r.json();
  })
  .then(function(data) {
    if (data.type === 'document' && data.document) {
      // Inject the document directly into the editor tabs — no re-fetch needed
      // since the API response already includes the full document dict. Stamps
      // _ocrTriggered so the PDF viewer doesn't re-run OCR on open (text was
      // already extracted during import).
      var docData = data.document;
      docData._ocrTriggered = true;
      import('./document.js').then(function(mod) {
        var inject = mod.injectFreshDoc
          || (mod.default && mod.default.injectFreshDoc);
        if (inject) {
          inject(docData);
        } else {
          // Fallback: use loadDocument (will re-fetch)
          var load = mod.loadDocument || (mod.default && mod.default.loadDocument);
          if (load) load(docData.id);
        }
      }).catch(function() {
        if (window.documentModule && window.documentModule.injectFreshDoc) {
          window.documentModule.injectFreshDoc(docData);
        } else if (window.documentModule && window.documentModule.loadDocument) {
          window.documentModule.loadDocument(docData.id);
        }
      });
    } else if (data.type === 'gallery_image' && data.image) {
      // Open the Gallery — the imported image appears in the grid.
      import('./gallery.js').then(function(mod) {
        var openGallery = mod.openGallery
          || (mod.default && mod.default.openGallery);
        if (openGallery) openGallery();
      }).catch(function() {
        // Fallback: try window.galleryModule
        if (window.galleryModule && window.galleryModule.openGallery) {
          window.galleryModule.openGallery();
        }
      });
    }
  })
  .catch(function(err) {
    // Show error via UI module if available
    if (window.uiModule && window.uiModule.showError) {
      window.uiModule.showError('Failed to open file: ' + (err.message || err));
    } else {
      alert('Failed to open file: ' + (err.message || err));
    }
  });
}

function _ncOpenFile(accountId, entry) {
  // Route to the appropriate Odysseus asset viewer.
  if (_ncIsText(entry)) return _ncOpenInAsset(accountId, entry);  // text/code → document editor
  if (_ncIsPdf(entry))  return _ncOpenInAsset(accountId, entry);  // PDF → PDF viewer
  if (_ncIsImage(entry)) return _ncOpenInAsset(accountId, entry); // image → Gallery
  window.open(_ncFileUrl(accountId, entry.path), '_blank');       // other → new tab
}

async function _ncFetchList(accountId, path) {
  const url = '/api/nextcloud/list?account=' + encodeURIComponent(accountId) + '&path=' + encodeURIComponent(path);
  const r = await fetch(url, { credentials: 'same-origin' });
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.json()).detail || ''; } catch (_) {}
    throw new Error(detail || ('HTTP ' + r.status));
  }
  return (await r.json()).entries || [];
}

window.openNextcloudExplorer = function (accountId, label) {
  if (!accountId) return;
  // Backdrop.
  const backdrop = document.createElement('div');
  backdrop.className = 'nc-explorer-backdrop';
  backdrop.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;padding:24px;';

  const panel = document.createElement('div');
  panel.style.cssText = 'background:var(--panel,#111);border:1px solid var(--border);border-radius:10px;width:min(760px,100%);height:min(82vh,680px);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.4);';

  // Header.
  const header = document.createElement('div');
  header.style.cssText = 'display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border);';
  const title = document.createElement('div');
  title.style.cssText = 'font-weight:600;font-size:13px;display:flex;align-items:center;gap:6px;color:var(--accent,var(--red));flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  title.innerHTML = _ncIcon('folder');
  const titleText = document.createElement('span');
  titleText.textContent = 'Nextcloud' + (label ? ' — ' + label : '');
  title.appendChild(titleText);
  const closeBtn = document.createElement('button');
  closeBtn.title = 'Close';
  closeBtn.style.cssText = 'background:none;border:none;color:var(--fg);cursor:pointer;padding:4px;display:inline-flex;opacity:0.7;';
  closeBtn.innerHTML = _ncIcon('close');
  closeBtn.onclick = () => backdrop.remove();
  header.appendChild(title);
  header.appendChild(closeBtn);

  // Breadcrumbs.
  const crumbs = document.createElement('div');
  crumbs.style.cssText = 'display:flex;align-items:center;gap:4px;padding:8px 12px;border-bottom:1px solid var(--border);font-size:12px;flex-wrap:wrap;';

  // Body (scrollable listing).
  const body = document.createElement('div');
  body.style.cssText = 'flex:1;overflow-y:auto;padding:6px 8px;font-size:12px;';

  // Status line.
  const status = document.createElement('div');
  status.style.cssText = 'padding:8px 12px;border-top:1px solid var(--border);font-size:11px;opacity:0.6;min-height:20px;';

  panel.appendChild(header);
  panel.appendChild(crumbs);
  panel.appendChild(body);
  panel.appendChild(status);
  backdrop.appendChild(panel);
  document.body.appendChild(backdrop);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) backdrop.remove(); });
  const onKey = (e) => { if (e.key === 'Escape') { backdrop.remove(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);

  let currentPath = '';

  function renderCrumbs() {
    crumbs.innerHTML = '';
    const root = document.createElement('button');
    root.textContent = '/';
    root.style.cssText = 'background:none;border:none;color:var(--accent,var(--red));cursor:pointer;font:inherit;padding:2px 4px;';
    root.onclick = () => navigate('');
    crumbs.appendChild(root);
    if (!currentPath) return;
    const segs = currentPath.split('/').filter(Boolean);
    let acc = '';
    segs.forEach((seg, i) => {
      acc = acc ? acc + '/' + seg : seg;
      const sep = document.createElement('span');
      sep.textContent = '/';
      sep.style.opacity = '0.4';
      crumbs.appendChild(sep);
      const isLast = i === segs.length - 1;
      const b = document.createElement('button');
      b.textContent = seg;
      b.style.cssText = 'background:none;border:none;font:inherit;padding:2px 4px;cursor:pointer;color:' + (isLast ? 'var(--fg)' : 'var(--accent,var(--red))') + ';';
      if (!isLast) b.onclick = () => navigate(acc);
      crumbs.appendChild(b);
    });
  }

  function navigate(path) {
    currentPath = (path || '').replace(/^\/+|\/+$/g, '');
    renderCrumbs();
    body.innerHTML = '';
    const loading = document.createElement('div');
    loading.textContent = 'Loading…';
    loading.style.cssText = 'padding:16px;opacity:0.6;';
    body.appendChild(loading);
    status.textContent = '/' + (currentPath || '');
    _ncFetchList(accountId, currentPath).then((entries) => {
      body.innerHTML = '';
      const dirs = entries.filter(e => e.is_dir).sort((a, b) => a.name.localeCompare(b.name));
      const files = entries.filter(e => !e.is_dir).sort((a, b) => a.name.localeCompare(b.name));
      if (dirs.length === 0 && files.length === 0) {
        const empty = document.createElement('div');
        empty.textContent = 'This folder is empty.';
        empty.style.cssText = 'padding:16px;opacity:0.6;';
        body.appendChild(empty);
        return;
      }
      const _makeActionBtn = (entry, iconName, title, onClick) => {
        const btn = document.createElement('button');
        btn.title = title;
        btn.style.cssText = 'background:color-mix(in srgb, var(--accent,var(--red)) 12%, transparent);border:1px solid color-mix(in srgb, var(--accent,var(--red)) 30%, transparent);color:var(--accent,var(--red));cursor:pointer;padding:3px 8px;display:inline-flex;align-items:center;gap:4px;border-radius:4px;font:inherit;font-size:11px;flex-shrink:0;white-space:nowrap;transition:background .15s,border-color .15s;';
        btn.innerHTML = _ncIcon(iconName) + '<span style="margin-left:1px">' + title + '</span>';
        btn.onmouseenter = function() { btn.style.background = 'color-mix(in srgb, var(--accent,var(--red)) 22%, transparent)'; btn.style.borderColor = 'var(--accent,var(--red))'; };
        btn.onmouseleave = function() { btn.style.background = 'color-mix(in srgb, var(--accent,var(--red)) 12%, transparent)'; btn.style.borderColor = 'color-mix(in srgb, var(--accent,var(--red)) 30%, transparent)'; };
        btn.onclick = function(e) { e.stopPropagation(); onClick(); };
        return btn;
      };

      const rowFor = (entry) => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:6px;cursor:pointer;';
        const ico = document.createElement('span');
        ico.style.cssText = 'display:inline-flex;color:var(--accent,var(--red));opacity:0.8;flex-shrink:0;';
        ico.innerHTML = entry.is_dir ? _ncIcon('folder') : _ncIcon('file');
        const name = document.createElement('span');
        name.textContent = entry.name + (entry.is_dir ? '/' : '');
        name.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
        const meta = document.createElement('span');
        meta.style.cssText = 'opacity:0.5;font-size:11px;flex-shrink:0;';
        meta.textContent = entry.is_dir ? '' : _ncHumanSize(entry.size);
        row.appendChild(ico);
        row.appendChild(name);
        row.appendChild(meta);

        // Action buttons for supported file types
        if (!entry.is_dir) {
          if (_ncIsText(entry)) {
            row.appendChild(_makeActionBtn(entry, 'edit', 'Open in editor', () => _ncOpenInAsset(accountId, entry)));
          } else if (_ncIsPdf(entry)) {
            row.appendChild(_makeActionBtn(entry, 'eye', 'Open in viewer', () => _ncOpenInAsset(accountId, entry)));
          } else if (_ncIsImage(entry)) {
            row.appendChild(_makeActionBtn(entry, 'image', 'Open in gallery', () => _ncOpenInAsset(accountId, entry)));
          }
        }

        row.onmouseenter = () => { row.style.background = 'color-mix(in srgb, var(--fg) 8%, transparent)'; };
        row.onmouseleave = () => { row.style.background = 'transparent'; };
        if (entry.is_dir) {
          row.onclick = () => navigate(entry.path);
        } else {
          row.onclick = () => _ncOpenFile(accountId, entry);
        }
        return row;
      };
      dirs.forEach(d => body.appendChild(rowFor(d)));
      files.forEach(f => body.appendChild(rowFor(f)));
      status.textContent = '/' + (currentPath || '') + '  ·  ' + dirs.length + ' folder' + (dirs.length === 1 ? '' : 's') + ', ' + files.length + ' file' + (files.length === 1 ? '' : 's');
    }).catch((e) => {
      body.innerHTML = '';
      const err = document.createElement('div');
      err.style.cssText = 'padding:16px;color:var(--red);';
      err.textContent = 'Could not list this folder: ' + (e.message || e);
      body.appendChild(err);
      status.textContent = '';
    });
  }

  navigate('');
};

// ── Library tab: read-only folder tree of all configured Nextcloud accounts ──

const _NC_CHEV = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';

function _ncRow(depth) {
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:7px;padding:4px 6px;cursor:pointer;border-radius:5px;';
  row.style.paddingLeft = (6 + depth * 14) + 'px';
  return row;
}

function _ncHover(row) {
  row.onmouseenter = () => { row.style.background = 'color-mix(in srgb, var(--fg) 8%, transparent)'; };
  row.onmouseleave = () => { row.style.background = 'transparent'; };
}

function _ncFileNode(accountId, entry, depth) {
  const row = _ncRow(depth);
  row.style.cursor = 'pointer';
  const spacer = document.createElement('span');
  spacer.style.cssText = 'display:inline-block;width:10px;flex-shrink:0;';
  const ico = document.createElement('span');
  ico.style.cssText = 'display:inline-flex;color:var(--accent,var(--red));opacity:0.7;flex-shrink:0;';
  ico.innerHTML = _ncIcon('file');
  const name = document.createElement('span');
  name.textContent = entry.name;
  name.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  const meta = document.createElement('span');
  meta.style.cssText = 'opacity:0.5;font-size:11px;flex-shrink:0;';
  meta.textContent = _ncHumanSize(entry.size);
  row.appendChild(spacer); row.appendChild(ico); row.appendChild(name); row.appendChild(meta);

  // Action button for supported types
  var actTitle, actIcon;
  if (_ncIsText(entry))  { actTitle = 'Open in editor'; actIcon = 'edit'; }
  if (_ncIsPdf(entry))   { actTitle = 'Open in viewer'; actIcon = 'eye'; }
  if (_ncIsImage(entry)) { actTitle = 'Open in gallery'; actIcon = 'image'; }
  if (actIcon) {
    var btn = document.createElement('button');
    btn.title = actTitle;
    btn.style.cssText = 'background:color-mix(in srgb, var(--accent,var(--red)) 12%, transparent);border:1px solid color-mix(in srgb, var(--accent,var(--red)) 30%, transparent);color:var(--accent,var(--red));cursor:pointer;padding:2px 6px;display:inline-flex;align-items:center;gap:3px;border-radius:4px;font:inherit;font-size:10px;flex-shrink:0;white-space:nowrap;transition:background .15s,border-color .15s;margin-left:6px;';
    btn.innerHTML = _ncIcon(actIcon);
    btn.onmouseenter = function() { btn.style.background = 'color-mix(in srgb, var(--accent,var(--red)) 22%, transparent)'; btn.style.borderColor = 'var(--accent,var(--red))'; };
    btn.onmouseleave = function() { btn.style.background = 'color-mix(in srgb, var(--accent,var(--red)) 12%, transparent)'; btn.style.borderColor = 'color-mix(in srgb, var(--accent,var(--red)) 30%, transparent)'; };
    btn.onclick = function(e) { e.stopPropagation(); _ncOpenInAsset(accountId, entry); };
    row.appendChild(btn);
  }

  _ncHover(row);
  row.onclick = () => _ncOpenFile(accountId, entry);
  return row;
}

function _ncFolderNode(accountId, label, path, depth) {
  const wrap = document.createElement('div');
  const row = _ncRow(depth);
  const chev = document.createElement('span');
  chev.style.cssText = 'display:inline-flex;opacity:0.6;flex-shrink:0;transition:transform 0.15s;';
  chev.innerHTML = _NC_CHEV;
  const ico = document.createElement('span');
  ico.style.cssText = 'display:inline-flex;color:var(--accent,var(--red));opacity:0.85;flex-shrink:0;';
  ico.innerHTML = _ncIcon('folder');
  const name = document.createElement('span');
  name.textContent = label + (path ? '' : '');
  name.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:' + (depth === 0 ? '600' : '400') + ';';
  row.appendChild(chev); row.appendChild(ico); row.appendChild(name);
  _ncHover(row);
  const kids = document.createElement('div');
  kids.style.cssText = 'display:none;';
  wrap.appendChild(row); wrap.appendChild(kids);
  let loaded = false;
  row.onclick = () => {
    const open = kids.style.display !== 'none';
    if (open) {
      kids.style.display = 'none';
      chev.style.transform = 'rotate(0deg)';
      return;
    }
    kids.style.display = '';
    chev.style.transform = 'rotate(90deg)';
    if (loaded) return;
    loaded = true;
    const loading = document.createElement('div');
    loading.textContent = 'Loading…';
    loading.style.cssText = 'padding:4px 6px;opacity:0.6;';
    kids.appendChild(loading);
    _ncFetchList(accountId, path).then((entries) => {
      kids.innerHTML = '';
      const dirs = entries.filter(e => e.is_dir).sort((a, b) => a.name.localeCompare(b.name));
      const files = entries.filter(e => !e.is_dir).sort((a, b) => a.name.localeCompare(b.name));
      if (!dirs.length && !files.length) {
        const empty = document.createElement('div');
        empty.textContent = 'Empty folder';
        empty.style.cssText = 'padding:4px 6px;opacity:0.5;';
        kids.appendChild(empty);
        return;
      }
      dirs.forEach(d => kids.appendChild(_ncFolderNode(accountId, d.name, d.path, depth + 1)));
      files.forEach(f => kids.appendChild(_ncFileNode(accountId, f, depth + 1)));
    }).catch((e) => {
      kids.innerHTML = '';
      const err = document.createElement('div');
      err.style.cssText = 'padding:4px 6px;color:var(--red);';
      err.textContent = 'Could not list folder: ' + (e.message || e);
      kids.appendChild(err);
    });
  };
  return wrap;
}

window.renderNextcloudLibrary = function () {
  const root = document.getElementById('doclib-nextcloud-tree');
  if (!root) return;
  root.innerHTML = '';
  const loading = document.createElement('div');
  loading.textContent = 'Loading…';
  loading.style.cssText = 'padding:10px;opacity:0.6;';
  root.appendChild(loading);
  fetch('/api/nextcloud/accounts', { credentials: 'same-origin' })
    .then(r => r.ok ? r.json() : { accounts: [] })
    .then((d) => {
      root.innerHTML = '';
      const accounts = (d && d.accounts) || [];
      if (!accounts.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'padding:10px;opacity:0.6;';
        empty.textContent = 'No Nextcloud account configured. Add one in Settings \u2192 Integrations.';
        root.appendChild(empty);
        return;
      }
      accounts.forEach(acc => {
        const label = acc.label || acc.username || 'Nextcloud';
        root.appendChild(_ncFolderNode(acc.id, label, '', 0));
      });
    })
    .catch(() => {
      root.innerHTML = '';
      const err = document.createElement('div');
      err.style.cssText = 'padding:10px;color:var(--red);';
      err.textContent = 'Could not load Nextcloud accounts.';
      root.appendChild(err);
    });
};

