// 共享鉴权与请求工具：所有页面通过此脚本访问后端 API。
// 若部署环境不同，只需改这一处 API_BASE（或通过 URL 参数 ?api= 覆盖）。
(function () {
  const params = new URLSearchParams(location.search);
  // 默认同源（前端 nginx 会把 /api 反代到后端）；可用 ?api=http://localhost:8000 临时覆盖。
  window.API_BASE = params.get("api") || "";
})();

const TOKEN_KEY = "procurement_token";
const ROLE_KEY = "procurement_role";

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setSession(token, role) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(ROLE_KEY, role);
}
function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}
function currentRole() { return localStorage.getItem(ROLE_KEY); }

// 统一请求封装：自动附加 Bearer、处理 401 与错误信息。
async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (auth && token) headers["Authorization"] = "Bearer " + token;

  const res = await fetch(window.API_BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    clearSession();
    if (!location.pathname.endsWith("login.html")) location.href = "login.html";
    throw new Error("未登录或登录已过期");
  }
  if (!res.ok) {
    let detail = "请求失败 (" + res.status + ")";
    try {
      const data = await res.json();
      if (data && data.detail) detail = data.detail;
    } catch (_) { /* 忽略非 JSON 响应 */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// 需要登录：未登录跳登录页，返回当前用户。
async function requireAuth() {
  if (!getToken()) { location.href = "login.html"; return null; }
  try { return await api("/api/users/me"); }
  catch (_) { return null; }
}

// 需要特定角色：非该角色重定向到其首页。
async function requireRole(role) {
  const me = await requireAuth();
  if (!me) return null;
  if (me.role !== role) {
    alert("无权访问该页面");
    location.href = me.role === "admin" ? "admin.html" : (me.role === "purchaser" ? "purchaser.html" : "index.html");
    return null;
  }
  return me;
}

function logout() { clearSession(); location.href = "login.html"; }

// 金额：按币种格式化。CNY 后端以「分」存储（除 100），JPY 以「円」整数存储（不除），其他本币按整数显示。
// 符号表与 backend/app/countries.yml 保持一致（新增国家时同步维护）。
const CURRENCY_SYMBOL = { CNY: "¥", JPY: "¥", USD: "$", KRW: "₩", HKD: "HK$", EUR: "€", GBP: "£" };
function money(cents, currency = "CNY") {
  const v = cents ?? 0;
  const sym = CURRENCY_SYMBOL[currency] || "¥";
  if (currency === "JPY") return sym + " " + v.toLocaleString("zh-CN") + " 円";
  if (currency === "CNY") return sym + " " + (v / 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return sym + " " + v.toLocaleString("zh-CN");
}

// 按币种分组合计，避免日元与人民币混加。items 形如 [{unit_price_cents, quantity, product:{currency}}]
function moneyGroup(items) {
  const groups = {};
  for (const i of items || []) {
    const c = (i.product && i.product.currency) || "CNY";
    groups[c] = (groups[c] || 0) + (i.unit_price_cents || 0) * (i.quantity || 0);
  }
  const parts = Object.entries(groups).map(([c, v]) => money(v, c));
  return parts.join(" + ") || money(0);
}

// 商品库价格展示：录入原价统一视为税前价；含税价和人民币价来自后端统一算法。
function priceText(p) {
  const original = money(p.pretax_price_cents ?? p.price_cents, p.currency);
  const taxed = money(p.taxed_price_cents, p.currency);
  const cny = money(p.price_cny_cents, "CNY");
  return `<span class="price-stack"><span>税前原价 ${original}</span><span>含税价 ${taxed}</span><span>人民币 ${cny}</span></span>`;
}

// 清单统一折算人民币合计（分）。依赖后端在 cart item 上返回的 price_cny_cents。
function cnyTotal(items) {
  return (items || []).reduce((s, i) => s + (i.price_cny_cents || 0) * (i.quantity || 0), 0);
}

// 姓名的首字母/前两字，用于头像。
function initials(name) {
  if (!name) return "?";
  return name.replace(/\s+/g, "").slice(0, 2).toUpperCase();
}

// HTML 转义（防止外部数据注入）。
function escHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 图片加载失败时回退为文字首字母块。
function thumbError(img) {
  const parent = img.parentNode;
  if (parent) parent.textContent = parent.getAttribute("data-ini") || "?";
}

// 商品缩略图：有图显示图（失败回退首字母），无图直接首字母。cls 为容器类名。
function productThumb(p, cls) {
  const ini = initials(p && p.name);
  const c = cls || "thumb";
  if (p && p.image_url) {
    return `<span class="${c} thumb-trigger" data-ini="${escHtml(ini)}" data-caption="${escHtml(p.name || "商品图片")}" tabindex="0" role="button" aria-label="查看商品图片：${escHtml(p.name || "商品图片")}"><img src="${escHtml(p.image_url)}" alt="${escHtml(p.name || "商品图片")}" width="52" height="52" loading="lazy" onerror="thumbError(this)"></span>`;
  }
  return `<span class="${c}">${escHtml(ini)}</span>`;
}

// 条目缩略图：优先手工上传的本地图（image_data，dataURL），其次商品库外链图（image_url）。
function itemThumb(item, cls) {
  const p = (item && item.product) || {};
  const ini = initials(p.name);
  const c = cls || "thumb";
  const src = (item && item.image_data) || p.image_url || null;
  if (src) {
    return `<span class="${c} thumb-trigger" data-ini="${escHtml(ini)}" data-caption="${escHtml(p.name || "商品图片")}" tabindex="0" role="button" aria-label="查看商品图片：${escHtml(p.name || "商品图片")}"><img src="${escHtml(src)}" alt="${escHtml(p.name || "商品图片")}" width="52" height="52" loading="lazy" onerror="thumbError(this)"></span>`;
  }
  return `<span class="${c}">${escHtml(ini)}</span>`;
}

// 仅当条目有图（上传图或外链图）时返回缩略图 span；无图返回空串（不占位）。
function itemThumbOptional(item, cls) {
  const src = (item && (item.image_data || (item.product && item.product.image_url))) || null;
  if (!src) return "";
  const p = (item && item.product) || {};
  const ini = initials(p.name);
  const c = cls || "thumb";
  return `<span class="${c} thumb-trigger" data-ini="${escHtml(ini)}" data-caption="${escHtml(p.name || "商品图片")}" tabindex="0" role="button" aria-label="查看商品图片：${escHtml(p.name || "商品图片")}"><img src="${escHtml(src)}" alt="${escHtml(p.name || "商品图片")}" width="52" height="52" loading="lazy" onerror="thumbError(this)"></span>`;
}

// 状态 -> 中文标签与样式类
const STATUS_LABELS = {
  draft: "草稿",
  submitted: "待处理",
  locked: "已锁定",
  success: "采购成功",
  failed: "采购失败",
};

// ===== 商品缩略图点击放大（灯箱，全站通用，事件委托） =====
let _zoomInited = false;
function initImageZoom() {
  if (_zoomInited) return;
  _zoomInited = true;
  const mask = document.createElement("div");
  mask.className = "zoom-mask";
  mask.setAttribute("role", "dialog");
  mask.setAttribute("aria-modal", "true");
  mask.setAttribute("aria-label", "商品图片预览");
  mask.innerHTML = `<button class="zoom-close" aria-label="关闭预览">×</button><img class="zoom-img" alt="商品图片预览" width="1200" height="900" src=""><div class="zoom-cap" aria-live="polite"></div>`;
  document.body.appendChild(mask);
  mask.addEventListener("click", e => {
    if (e.target === mask || e.target.classList.contains("zoom-close")) closeZoom();
  });
  mask.addEventListener("keydown", e => {
    if (e.key === "Tab") {
      const close = mask.querySelector(".zoom-close");
      e.preventDefault();
      close.focus();
    }
  });
  document.addEventListener("click", e => {
    const t = e.target;
      if (t && t.tagName === "IMG" && t.closest(".thumb-trigger")) {
      const trigger = t.closest(".thumb-trigger");
      const src = t.getAttribute("src");
      if (!src) return;
      e.preventDefault();
      e.stopPropagation();
      openZoom(src, trigger.getAttribute("data-caption") || trigger.getAttribute("data-ini") || "", trigger);
    }
  });
  document.addEventListener("keydown", e => {
    const trigger = e.target && e.target.closest ? e.target.closest(".thumb-trigger") : null;
    if (trigger && (e.key === "Enter" || e.key === " ")) {
      const img = trigger.querySelector("img");
      if (img && img.src) { e.preventDefault(); openZoom(img.src, trigger.getAttribute("data-caption") || trigger.getAttribute("data-ini") || "", trigger); }
    }
    if (e.key === "Escape") closeZoom();
  });
}
let _zoomReturnFocus = null;
function openZoom(src, caption, trigger) {
  const mask = document.querySelector(".zoom-mask");
  if (!mask) return;
  const img = mask.querySelector(".zoom-img");
  const cap = mask.querySelector(".zoom-cap");
  _zoomReturnFocus = trigger || document.activeElement;
  img.src = src;
  img.onerror = () => { mask.classList.remove("show"); };
  img.onload = () => { cap.textContent = caption || ""; mask.classList.add("show"); mask.querySelector(".zoom-close").focus(); };
  // 确保即使缓存命中也能正常显示，避免 onload 未触发
  if (img.complete && img.naturalWidth) { cap.textContent = caption || ""; mask.classList.add("show"); mask.querySelector(".zoom-close").focus(); }
}
function closeZoom() {
  const mask = document.querySelector(".zoom-mask");
  if (mask) mask.classList.remove("show");
  if (_zoomReturnFocus && typeof _zoomReturnFocus.focus === "function") { _zoomReturnFocus.focus(); _zoomReturnFocus = null; }
}
// 页面脚本加载后自动初始化（各页可随时调用；幂等）
try { initImageZoom(); } catch (e) { /* 忽略 */ }
