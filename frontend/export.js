// 分人对账 + 采购合并导出：弹窗选批次/版式 → 当前页打印预览（打印对话框可选「存储为 PDF」）。
// 依赖 auth.js 的 escHtml / money / STATUS_LABELS。
(function () {
  if (window.ExportRecon) return;

  const STYLE_ID = "xrecon-style";
  const CSS = `
    .xrecon-title-row { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; width:100%; }
    .xrecon-btn { border:1px solid var(--line,#e6dfd3); background:#fff; color:var(--green,#28725a); border-radius:5px; padding:6px 12px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap; }
    .xrecon-btn:hover { border-color:var(--green,#28725a); color:var(--green-dark,#1e5e49); }
    .xrecon-btn.primary { background:var(--green,#28725a); border-color:var(--green,#28725a); color:#fff; }
    .xrecon-btn.primary:hover { background:var(--green-dark,#1e5e49); color:#fff; }
    .xrecon-mask { position:fixed; inset:0; z-index:10050; background:rgba(37,49,45,.38); display:flex; align-items:center; justify-content:center; padding:18px; }
    .xrecon-dlg { background:var(--surface,#fffdfa); color:var(--ink,#25312d); border:1px solid var(--line,#e6dfd3); border-radius:10px; width:min(520px,100%); max-height:min(86vh,680px); overflow:auto; padding:18px 18px 16px; box-shadow:0 18px 48px rgba(37,49,45,.18); }
    .xrecon-dlg h3 { margin:0 0 4px; font-size:16px; }
    .xrecon-dlg .xr-tip { margin:0 0 12px; color:var(--muted,#7b847f); font-size:12px; line-height:1.55; }
    .xrecon-sec { font-size:11px; font-weight:800; color:var(--muted,#7b847f); margin:12px 0 6px; }
    .xrecon-batches { display:flex; flex-direction:column; gap:6px; max-height:200px; overflow:auto; padding:2px 0; }
    .xrecon-opt { display:flex; align-items:flex-start; gap:8px; font-size:13px; cursor:pointer; }
    .xrecon-opt input { margin-top:2px; }
    .xrecon-empty { color:var(--muted,#7b847f); font-size:12px; padding:6px 0; }
    .xrecon-acts { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
    #xrecon-print { display:none; }
    #xrecon-print .xrecon-toolbar { position:sticky; top:0; z-index:1; display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:12px 16px; background:#fffdfa; border-bottom:1px solid #e6dfd3; }
    #xrecon-print .xrecon-sheet { max-width:860px; margin:0 auto; padding:22px 18px 48px; color:#25312d; }
    .xrecon-h1 { margin:0 0 4px; font-size:20px; }
    .xrecon-sub { color:#7b847f; font-size:12px; line-height:1.6; margin:0 0 16px; }
    .xrecon-person, .xrecon-sku { margin:0 0 22px; border:1px solid #e6dfd3; border-radius:8px; overflow:hidden; background:#fff; }
    .xrecon-phead { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 14px; padding:10px 14px; background:#fbf8f0; border-bottom:1px solid #e6dfd3; }
    .xrecon-pname { font-weight:800; font-size:14px; }
    .xrecon-pmeta { color:#7b847f; font-size:11px; }
    .xrecon-row { display:grid; grid-template-columns:minmax(0,1.4fr) auto minmax(120px,auto) minmax(120px,auto); gap:8px 12px; align-items:start; padding:10px 14px; border-bottom:1px solid #f0ece5; font-size:12px; }
    .xrecon-row:last-child { border-bottom:0; }
    .xrecon-row.purchased .xr-name b, .xrecon-sku.purchased .xrecon-pname { text-decoration:line-through; color:#7b847f; }
    .xr-name b { font-size:13px; }
    .xr-meta { display:block; color:#7b847f; font-size:11px; margin-top:3px; }
    .xr-who { display:block; color:#496258; font-size:11px; margin-top:5px; line-height:1.55; }
    .xr-note { margin-top:5px; font-size:11px; color:#7d6a3c; background:#fff0d5; border-radius:4px; padding:3px 7px; line-height:1.5; word-break:break-word; }
    .xr-note.proc { color:#3a5d4a; background:#eef4ee; }
    .xr-qty { font-weight:750; white-space:nowrap; padding-top:1px; }
    .xr-price, .xr-sum { color:#496258; font-size:11px; line-height:1.55; white-space:nowrap; text-align:right; }
    .xr-sum { font-weight:750; }
    .xrecon-ptotal { display:flex; flex-wrap:wrap; gap:8px 16px; padding:10px 14px; background:#fbfaf6; border-top:1px solid #e6dfd3; font-size:12px; }
    .xrecon-ptotal b { font-weight:800; }
    .xrecon-grand { margin-top:8px; padding:12px 14px; border:1px solid #e6dfd3; border-radius:8px; background:#fffdfa; }
    .xrecon-grand .g-t { font-weight:800; margin-bottom:6px; }
    .xrecon-none { padding:28px 14px; text-align:center; color:#7b847f; font-size:13px; }
    .xr-mark { display:inline-block; margin-left:6px; padding:1px 6px; border-radius:999px; background:#e5f0e9; color:#28725a; font-size:10px; font-weight:700; }
    .xrecon-part { margin:0 0 8px; }
    .xrecon-part + .xrecon-part { margin-top:28px; padding-top:8px; }
    @media screen {
      body.xrecon-printing { overflow:hidden; }
      body.xrecon-printing #xrecon-print { display:block; position:fixed; inset:0; z-index:10040; background:#f6f2e9; overflow:auto; }
    }
    @media print {
      @page { size: A4 portrait; margin: 12mm 10mm 14mm; }
      body.xrecon-printing > *:not(#xrecon-print) { display:none !important; }
      body.xrecon-printing #xrecon-print { display:block !important; position:static; background:#fff; overflow:visible; }
      #xrecon-print .xrecon-toolbar { display:none !important; }
      #xrecon-print .xrecon-sheet { max-width:none; padding:0; }
      .xrecon-person, .xrecon-sku { break-inside:auto; }
      .xrecon-phead, .xrecon-row { break-inside:avoid; }
      .xrecon-row { grid-template-columns:minmax(0,1.3fr) auto minmax(110px,auto) minmax(110px,auto); }
      .xrecon-part + .xrecon-part { break-before: page; margin-top:0; padding-top:0; }
    }
    @media (max-width: 640px) {
      .xrecon-row { grid-template-columns:minmax(0,1fr) auto; }
      .xr-price, .xr-sum { text-align:left; }
    }
  `;

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  function fmtDate(d) {
    if (!d) return "";
    const parts = String(d).split("-");
    if (parts.length < 3) return d;
    return parts[0] + "年" + +parts[1] + "月" + +parts[2] + "日";
  }
  function nowText() {
    try { return new Date().toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
    catch (_) { return ""; }
  }
  function batchLabel(b) {
    if (b.batch_no > 0) return "第 " + b.batch_no + " 批";
    return b.status === "draft" ? "新清单" : (b.batch_no === 0 ? "新清单" : "批次");
  }
  function stLabel(st) { return (STATUS_LABELS && STATUS_LABELS[st]) || st || ""; }
  function personName(p) { return (p && (p.full_name || p.email)) || "未署名"; }
  function personKey(p) { return String((p && (p.id != null ? p.id : p.email)) || "unknown"); }

  function collectBatches(opts) {
    const map = new Map();
    for (const b of opts.batches || []) {
      const cid = b.cart_id != null ? b.cart_id : b.id;
      if (cid == null) continue;
      map.set(cid, {
        cart_id: cid,
        batch_no: b.batch_no || 0,
        status: b.status || "",
        count: b.count || 0,
        who: b.who || (b.requester ? personName(b.requester) : ""),
      });
    }
    for (const it of opts.items || []) {
      if (it.cart_id == null) continue;
      if (!map.has(it.cart_id)) {
        map.set(it.cart_id, {
          cart_id: it.cart_id,
          batch_no: it.batch_no || 0,
          status: it.cart_status || "",
          count: 0,
          who: personName(it.requester),
        });
      }
    }
    return [...map.values()].sort((a, b) => (a.batch_no - b.batch_no) || (a.cart_id - b.cart_id));
  }

  function fieldVal(it, field) {
    if (field === "pretax_price_cents") return (it.pretax_price_cents ?? it.unit_price_cents) || 0;
    if (field === "taxed_price_cents") return (it.taxed_price_cents ?? it.pretax_price_cents ?? it.unit_price_cents) || 0;
    return it[field] || 0;
  }
  function sumField(items, field) {
    const g = {};
    for (const it of items) {
      const c = (it.product && it.product.currency) || "JPY";
      g[c] = (g[c] || 0) + fieldVal(it, field) * (it.quantity || 0);
    }
    const parts = Object.entries(g).map(([c, v]) => money(v, c));
    return parts.join(" + ") || money(0, "CNY");
  }
  function sumCny(items) {
    return items.reduce((s, i) => s + (i.price_cny_cents || 0) * (i.quantity || 0), 0);
  }
  function qtyOf(items) {
    return items.reduce((s, i) => s + (i.quantity || 0), 0);
  }

  function filterItems(items, selectedIds, allIfEmpty) {
    if (!selectedIds.size) return allIfEmpty ? items.slice() : [];
    return items.filter(it => it.cart_id == null || selectedIds.has(it.cart_id));
  }

  function groupPeople(items) {
    const map = new Map();
    for (const it of items) {
      const k = personKey(it.requester);
      if (!map.has(k)) map.set(k, { requester: it.requester || {}, rows: [] });
      map.get(k).rows.push(it);
    }
    const list = [...map.values()];
    list.sort((a, b) => personName(a.requester).localeCompare(personName(b.requester), "zh"));
    for (const p of list) {
      p.rows.sort((a, b) => (a.batch_no || 0) - (b.batch_no || 0) || String((a.product || {}).name || "").localeCompare(String((b.product || {}).name || ""), "zh"));
    }
    return list;
  }

  function mergeKey(it) {
    const p = it.product || {};
    const pid = p.id != null ? "id:" + p.id : "n:" + (p.name || "");
    return pid + "\0" + (it.color || "").trim().toLowerCase();
  }
  function groupMerged(items) {
    const map = new Map();
    for (const it of items) {
      const k = mergeKey(it);
      if (!map.has(k)) {
        map.set(k, {
          product: it.product || {},
          color: (it.color || "").trim(),
          rows: [],
        });
      }
      map.get(k).rows.push(it);
    }
    const list = [...map.values()];
    list.sort((a, b) => String(a.product.name || "").localeCompare(String(b.product.name || ""), "zh") || a.color.localeCompare(b.color, "zh"));
    return list;
  }
  function whoLine(rows) {
    const map = new Map();
    for (const it of rows) {
      const k = personKey(it.requester);
      if (!map.has(k)) map.set(k, { requester: it.requester || {}, qty: 0, batches: new Set() });
      const rec = map.get(k);
      rec.qty += it.quantity || 0;
      if (it.batch_no > 0) rec.batches.add(it.batch_no);
    }
    return [...map.values()]
      .sort((a, b) => personName(a.requester).localeCompare(personName(b.requester), "zh"))
      .map(rec => {
        const batches = [...rec.batches].sort((a, b) => a - b).map(n => "第" + n + "批").join("/");
        return personName(rec.requester) + " ×" + rec.qty + (batches ? "（" + batches + "）" : "");
      })
      .join(" · ");
  }
  function uniqueNotes(rows, pick) {
    const seen = new Set();
    const out = [];
    for (const it of rows) {
      const t = (pick(it) || "").trim();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      out.push(t);
    }
    return out;
  }
  function unitIfUniform(rows, field) {
    if (!rows.length) return null;
    const first = fieldVal(rows[0], field);
    return rows.every(it => fieldVal(it, field) === first) ? first : null;
  }

  function rowHtml(it, opts) {
    const p = it.product || {};
    const color = (it.color || "").trim();
    const typeBit = (p.category || "").trim();
    const meta = [
      color || null,
      typeBit ? "类型：" + typeBit : null,
      it.batch_no > 0 ? "第 " + it.batch_no + " 批" : (it.cart_status === "draft" ? "新清单" : null),
      stLabel(it.cart_status),
    ].filter(Boolean).join(" · ");
    const cur = p.currency || "JPY";
    const pretax = it.pretax_price_cents ?? it.unit_price_cents;
    const taxed = it.taxed_price_cents ?? pretax;
    const cny = it.price_cny_cents;
    const qty = it.quantity || 0;
    const noteUser = opts.userRemark ? (p.remark || "").trim() : "";
    const noteProc = opts.procRemark ? (it.procurement_remark || "").trim() : "";
    return `<div class="xrecon-row${it.purchased ? " purchased" : ""}">
      <div class="xr-name"><b>${escHtml(p.name || "未命名商品")}</b>${it.purchased ? '<span class="xr-mark">已采购</span>' : ""}<span class="xr-meta">${escHtml(meta)}</span>${noteUser ? `<div class="xr-note">需求备注：${escHtml(noteUser)}</div>` : ""}${noteProc ? `<div class="xr-note proc">采购备注：${escHtml(noteProc)}</div>` : ""}</div>
      <div class="xr-qty">× ${qty}</div>
      <div class="xr-price">税前 ${money(pretax, cur)}<br>含税 ${money(taxed, cur)}${cny != null ? "<br>人民币 " + money(cny, "CNY") : ""}</div>
      <div class="xr-sum">小计 ${money((taxed || 0) * qty, cur)}${cny != null ? "<br>≈ " + money(cny * qty, "CNY") : ""}</div>
    </div>`;
  }

  function peopleBody(ctx) {
    const people = groupPeople(ctx.items);
    if (!people.length) {
      return '<div class="xrecon-none">没有符合条件的条目。默认不含草稿，可在导出选项中勾选草稿批次。</div>';
    }
    let body = people.map(p => {
      const rows = p.rows;
      return `<section class="xrecon-person">
        <div class="xrecon-phead">
          <span class="xrecon-pname">${escHtml(personName(p.requester))}</span>
          <span class="xrecon-pmeta">${rows.length} 条 · ${qtyOf(rows)} 件</span>
        </div>
        ${rows.map(it => rowHtml(it, ctx)).join("")}
        <div class="xrecon-ptotal">
          <span>税前合计 <b>${sumField(rows, "pretax_price_cents")}</b></span>
          <span>含税合计 <b>${sumField(rows, "taxed_price_cents")}</b></span>
          <span>人民币 <b>${money(sumCny(rows), "CNY")}</b></span>
        </div>
      </section>`;
    }).join("");
    if (people.length > 1) {
      body += `<div class="xrecon-grand"><div class="g-t">组合计（${people.length} 人）</div>
        <div class="xrecon-ptotal" style="padding:0;border:0;background:transparent">
          <span>税前 <b>${sumField(ctx.items, "pretax_price_cents")}</b></span>
          <span>含税 <b>${sumField(ctx.items, "taxed_price_cents")}</b></span>
          <span>人民币 <b>${money(sumCny(ctx.items), "CNY")}</b></span>
        </div></div>`;
    }
    return body;
  }

  function mergeRowHtml(sku, opts) {
    const p = sku.product || {};
    const rows = sku.rows;
    const color = sku.color;
    const typeBit = (p.category || "").trim();
    const total = qtyOf(rows);
    const bought = qtyOf(rows.filter(it => it.purchased));
    const allBought = bought > 0 && bought === total;
    const cur = p.currency || "JPY";
    const pretaxU = unitIfUniform(rows, "pretax_price_cents");
    const taxedU = unitIfUniform(rows, "taxed_price_cents");
    const cnyU = rows.length && rows.every(it => (it.price_cny_cents || 0) === (rows[0].price_cny_cents || 0))
      ? (rows[0].price_cny_cents || 0) : null;
    const meta = [color || null, typeBit ? "类型：" + typeBit : null, rows.length + " 条合并"].filter(Boolean).join(" · ");
    const mark = allBought
      ? '<span class="xr-mark">已采购</span>'
      : (bought ? '<span class="xr-mark">已采购 ' + bought + "/" + total + "</span>" : "");
    const userNotes = opts.userRemark ? uniqueNotes(rows, it => (it.product && it.product.remark) || "") : [];
    const procNotes = opts.procRemark ? uniqueNotes(rows, it => it.procurement_remark || "") : [];
    const priceHtml = pretaxU != null
      ? `税前 ${money(pretaxU, cur)}<br>含税 ${money(taxedU != null ? taxedU : pretaxU, cur)}${cnyU != null ? "<br>人民币 " + money(cnyU, "CNY") : ""}`
      : `单价因价格组不同<br>含税合计 ${sumField(rows, "taxed_price_cents")}`;
    const sumHtml = pretaxU != null
      ? `小计 ${money((taxedU != null ? taxedU : pretaxU) * total, cur)}${cnyU != null ? "<br>≈ " + money(cnyU * total, "CNY") : ""}`
      : `人民币 ${money(sumCny(rows), "CNY")}`;
    return `<div class="xrecon-row${allBought ? " purchased" : ""}">
      <div class="xr-name"><b>${escHtml(p.name || "未命名商品")}</b>${mark}<span class="xr-meta">${escHtml(meta)}</span><span class="xr-who">${escHtml(whoLine(rows))}</span>${userNotes.map(t => `<div class="xr-note">需求备注：${escHtml(t)}</div>`).join("")}${procNotes.map(t => `<div class="xr-note proc">采购备注：${escHtml(t)}</div>`).join("")}</div>
      <div class="xr-qty">× ${total}</div>
      <div class="xr-price">${priceHtml}</div>
      <div class="xr-sum">${sumHtml}</div>
    </div>`;
  }

  function mergeBody(ctx) {
    const skus = groupMerged(ctx.items);
    if (!skus.length) {
      return '<div class="xrecon-none">没有符合条件的条目。默认不含草稿，可在导出选项中勾选草稿批次。</div>';
    }
    const inner = skus.map(sku => mergeRowHtml(sku, ctx)).join("");
    return `<section class="xrecon-sku">
      <div class="xrecon-phead">
        <span class="xrecon-pname">按商品合并</span>
        <span class="xrecon-pmeta">${skus.length} 种 · ${qtyOf(ctx.items)} 件</span>
      </div>
      ${inner}
      <div class="xrecon-ptotal">
        <span>税前合计 <b>${sumField(ctx.items, "pretax_price_cents")}</b></span>
        <span>含税合计 <b>${sumField(ctx.items, "taxed_price_cents")}</b></span>
        <span>人民币 <b>${money(sumCny(ctx.items), "CNY")}</b></span>
      </div>
    </section>`;
  }

  function headBits(ctx, extra) {
    const g = ctx.group || {};
    const range = (g.start_date || g.end_date) ? (fmtDate(g.start_date) + " ~ " + fmtDate(g.end_date)) : "";
    return [
      extra,
      range,
      "导出 " + nowText(),
      ctx.exporter ? ("导出人 " + ctx.exporter) : "",
      ctx.includeDraft ? "含草稿" : "不含草稿",
    ].filter(Boolean);
  }

  function reconTitle(ctx) {
    return ctx.title || "分人对账";
  }
  function mergeTitle(ctx) {
    const g = ctx.group || {};
    if (g.title) return g.title + " · 采购合并";
    const t = (ctx.title || "").replace(/的对账单$/, "").replace(/[·\s]*分人对账单$/, "").trim();
    return (t || "出游组") + " · 采购合并";
  }

  function sheetHtml(ctx) {
    const mode = ctx.mode || "both";
    const showRecon = mode === "recon" || mode === "both";
    const showMerge = mode === "merge" || mode === "both";
    const parts = [];
    if (showRecon) {
      parts.push(`<div class="xrecon-part">
        <h1 class="xrecon-h1">${escHtml(reconTitle(ctx))}</h1>
        <p class="xrecon-sub">${escHtml(headBits(ctx, "分人对账").join(" · "))}。本页为导出快照，金额以系统当时折算为准。</p>
        ${peopleBody(ctx)}
      </div>`);
    }
    if (showMerge) {
      parts.push(`<div class="xrecon-part">
        <h1 class="xrecon-h1">${escHtml(mergeTitle(ctx))}</h1>
        <p class="xrecon-sub">${escHtml(headBits(ctx, "按商品+颜色合并，便于买货").join(" · "))}。已采购会划线；部分已采购会标件数。本页为导出快照。</p>
        ${mergeBody(ctx)}
      </div>`);
    }
    return `<div class="xrecon-toolbar">
        <button type="button" class="xrecon-btn primary" data-xr="do-print">打印 / 存储为 PDF</button>
        <button type="button" class="xrecon-btn" data-xr="close-print">关闭预览</button>
        <span class="xr-tip" style="margin:0">电脑请在打印对话框选择「存储为 PDF」；手机可滚动长截图。</span>
      </div>
      <div class="xrecon-sheet">${parts.join("")}</div>`;
  }

  function closePrint() {
    const root = document.getElementById("xrecon-print");
    if (root) root.remove();
    document.body.classList.remove("xrecon-printing");
    if (closePrint._title != null) {
      document.title = closePrint._title;
      closePrint._title = null;
    }
  }

  function openPrint(ctx) {
    closePrint();
    closePrint._title = document.title;
    const label = ctx.mode === "merge" ? mergeTitle(ctx) : (ctx.mode === "both" ? (ctx.title || "清单") : reconTitle(ctx));
    const safeTitle = String(label || "清单").replace(/[\\/:*?"<>|]+/g, " ").trim();
    document.title = "清单-" + safeTitle + "-" + new Date().toISOString().slice(0, 10);
    const root = document.createElement("div");
    root.id = "xrecon-print";
    root.innerHTML = sheetHtml(ctx);
    document.body.appendChild(root);
    document.body.classList.add("xrecon-printing");
    root.addEventListener("click", (e) => {
      const act = e.target && e.target.getAttribute && e.target.getAttribute("data-xr");
      if (act === "do-print") window.print();
      if (act === "close-print") closePrint();
    });
    const btn = root.querySelector("[data-xr='do-print']");
    if (btn) btn.focus();
  }

  function closeDialog() {
    const mask = document.getElementById("xrecon-mask");
    if (mask) mask.remove();
  }

  function openDialog(opts) {
    ensureStyle();
    closeDialog();
    const batches = collectBatches(opts);
    const hasDraft = batches.some(b => b.status === "draft");
    const batchHtml = batches.length
      ? batches.map(b => {
          const checked = b.status !== "draft" ? " checked" : "";
          const who = b.who ? escHtml(b.who) + " · " : "";
          return `<label class="xrecon-opt"><input type="checkbox" data-cart="${b.cart_id}"${checked}>${who}${escHtml(batchLabel(b))} · ${escHtml(stLabel(b.status) || "—")} · ${b.count || 0} 件</label>`;
        }).join("")
      : '<div class="xrecon-empty">没有可导出的批次</div>';
    const mask = document.createElement("div");
    mask.id = "xrecon-mask";
    mask.className = "xrecon-mask";
    mask.innerHTML = `<div class="xrecon-dlg" role="dialog" aria-modal="true" aria-labelledby="xrecon-dlg-title">
      <h3 id="xrecon-dlg-title">导出清单</h3>
      <p class="xr-tip">${escHtml(opts.title || "")}${hasDraft ? "。草稿默认不导出，需要请勾选对应批次。" : "。"}已采购条目会保留并划线。</p>
      <div class="xrecon-sec">版式</div>
      <label class="xrecon-opt"><input type="radio" name="xr-mode" value="recon">分人对账（按人列明细）</label>
      <label class="xrecon-opt"><input type="radio" name="xr-mode" value="merge">采购合并（按商品+颜色汇总）</label>
      <label class="xrecon-opt"><input type="radio" name="xr-mode" value="both" checked>两份都出（先分人，再合并；打印时分页）</label>
      <div class="xrecon-sec">批次</div>
      <div class="xrecon-batches">${batchHtml}</div>
      <div class="xrecon-sec">附加信息</div>
      <label class="xrecon-opt"><input type="checkbox" data-xr="user-remark" checked>含需求人备注</label>
      <label class="xrecon-opt"><input type="checkbox" data-xr="proc-remark">含采购侧备注</label>
      <div class="xrecon-acts">
        <button type="button" class="xrecon-btn" data-xr="cancel">取消</button>
        <button type="button" class="xrecon-btn primary" data-xr="go">预览并打印</button>
      </div>
    </div>`;
    mask.addEventListener("click", (e) => {
      if (e.target === mask) closeDialog();
      const act = e.target && e.target.getAttribute && e.target.getAttribute("data-xr");
      if (act === "cancel") closeDialog();
      if (act === "go") {
        const selected = new Set();
        mask.querySelectorAll("input[data-cart]:checked").forEach(el => {
          const n = parseInt(el.getAttribute("data-cart"), 10);
          if (!Number.isNaN(n)) selected.add(n);
        });
        const items = filterItems(opts.items || [], selected, false);
        const includeDraft = batches.some(b => b.status === "draft" && selected.has(b.cart_id));
        const userRemark = !!mask.querySelector("input[data-xr='user-remark']")?.checked;
        const procRemark = !!mask.querySelector("input[data-xr='proc-remark']")?.checked;
        const modeEl = mask.querySelector("input[name='xr-mode']:checked");
        const mode = (modeEl && modeEl.value) || "both";
        closeDialog();
        openPrint({
          title: opts.title,
          group: opts.group,
          exporter: opts.exporter,
          items,
          userRemark,
          procRemark,
          includeDraft,
          mode,
        });
      }
    });
    document.body.appendChild(mask);
    const go = mask.querySelector("[data-xr='go']");
    if (go) go.focus();
  }

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (document.getElementById("xrecon-print")) { closePrint(); e.preventDefault(); return; }
    if (document.getElementById("xrecon-mask")) { closeDialog(); e.preventDefault(); }
  });

  ensureStyle();
  window.ExportRecon = { open: openDialog, close: closePrint };
})();
