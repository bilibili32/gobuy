#!/usr/bin/env bash
# 端到端冒烟测试：走完 注册 -> 登录 -> 搜索 -> 加购 -> 改数量 -> 提交(归入出游组)
#                        -> 管理员锁定 -> 采购成功 的完整业务链路，并覆盖出游采购组
#                        （建组/邀请码加入/批量拉人/到期停收/多组选择/跨采购员越权/上限）。
#
# 用法：
#   docker compose up -d           # 先起服务
#   ./scripts/smoke_test.sh        # 跑冒烟
#
# 依赖：curl、python3（仅用于解析 JSON）
set -euo pipefail

API="${API_BASE:-http://localhost:8000}"
ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${BOOTSTRAP_ADMIN_PASSWORD:-}"
STAMP=$(date +%s)
USER_EMAIL="smoke${STAMP}@example.com"
USER_PASSWORD="SmokeTest12345"

PASS=0
FAIL=0

# 从 JSON 中取值：json_get "$body" "access_token"
json_get() { python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1], ""))' "$2" <<<"$1"; }

check() { # check <描述> <实际> <期望>
  if [[ "$2" == *"$3"* ]]; then
    printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS + 1))
  else
    printf '  \033[31m✗\033[0m %s\n    期望包含: %s\n    实际收到: %s\n' "$1" "$3" "$2"; FAIL=$((FAIL + 1))
  fi
}

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

request() { # request <方法> <路径> [token] [json]
  local method=$1 path=$2 token=${3:-} data=${4:-}
  local -a args=(-sS -w '\n%{http_code}' -X "$method" "$API$path")
  [[ -n "$data" ]] && args+=(-H 'Content-Type: application/json' -d "$data")
  [[ -n "$token" ]] && args+=(-H "Authorization: Bearer $token")
  curl "${args[@]}"
}

# 返回：body 写入 $BODY，状态码写入 $CODE
BODY=""; CODE=""
call() {
  local out; out=$(request "$@")
  CODE=$(tail -n1 <<<"$out")
  BODY=$(sed '$d' <<<"$out")
}

# 出游日期区间：未来窗口（进行中）与过去窗口（已到期）
FUT1=$(python3 -c "from datetime import date,timedelta;print(date.today()+timedelta(days=1))")
FUT2=$(python3 -c "from datetime import date,timedelta;print(date.today()+timedelta(days=9))")
PAST1=$(python3 -c "from datetime import date,timedelta;print(date.today()-timedelta(days=4))")
PAST2=$(python3 -c "from datetime import date,timedelta;print(date.today()-timedelta(days=2))")

section "0. 服务可用性"
call GET /health
check "GET /health 返回 200" "$CODE" "200"
check "健康检查内容正确" "$BODY" '"status":"ok"'

section "1. 普通用户注册与登录"
call POST /api/auth/register "" \
  "{\"email\":\"$USER_EMAIL\",\"full_name\":\"冒烟测试\",\"password\":\"$USER_PASSWORD\"}"
check "注册返回 201" "$CODE" "201"
check "注册后角色为 user" "$BODY" '"role":"user"'

call POST /api/auth/login "" "{\"email\":\"$USER_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
USER_TOKEN=$(json_get "$BODY" access_token)
check "登录返回 200" "$CODE" "200"
check "登录拿到 access_token" "$USER_TOKEN" "."

call POST /api/auth/login "" "{\"email\":\"$USER_EMAIL\",\"password\":\"wrong-password\"}"
check "错误密码被拒绝 401" "$CODE" "401"

section "2. 商品搜索"
# 不依赖固定 seed 数据：取当前商品库第一件商品名称作为搜索词，避免清空/重复运行后因商品库内容变化误报。
call GET /api/products "$USER_TOKEN"
check "读取商品库返回 200" "$CODE" "200"
SEARCH_TERM=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print((d[0]["name"] if d else "").strip())' <<<"$BODY")
if [[ -n "$SEARCH_TERM" ]]; then
  SEARCH_Q=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$SEARCH_TERM")
  call GET "/api/products?q=$SEARCH_Q" "$USER_TOKEN"
  check "按商品名称搜索返回 200" "$CODE" "200"
  check "搜索命中当前商品" "$BODY" "$SEARCH_TERM"
else
  check "商品库至少有一件商品" "empty" "never"
fi

call GET /api/products ""
check "未带令牌访问商品被拒 401" "$CODE" "401"

section "3. 个人采购清单（草稿）"
call GET /api/carts/me "$USER_TOKEN"
check "读取个人清单 200" "$CODE" "200"
check "新清单状态为 draft" "$BODY" '"status":"draft"'

PRODUCT_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])' <<<"$(request GET /api/products "$USER_TOKEN" | sed '$d')" 2>/dev/null || echo 1)

call POST /api/carts/me/items "$USER_TOKEN" "{\"product_id\":$PRODUCT_ID,\"quantity\":2}"
check "加入商品返回 201" "$CODE" "201"
check "清单中出现该商品" "$BODY" '"quantity":2'

ITEM_ID=$(python3 - <<PY
import json
data = json.loads('''$BODY''')
print(data["items"][0]["id"])
PY
)
PROD_PRICE=$(python3 - <<PY
import json
data = json.loads('''$BODY''')
print(data["items"][0]["unit_price_cents"])
PY
)

call PATCH "/api/carts/me/items/$ITEM_ID" "$USER_TOKEN" '{"quantity":5}'
check "改数量返回 200" "$CODE" "200"
check "数量已更新为 5" "$BODY" '"quantity":5'

section "4. 越权防护"
OTHER_EMAIL="other${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$OTHER_EMAIL\",\"full_name\":\"另一个人\",\"password\":\"$USER_PASSWORD\"}"
call POST /api/auth/login "" "{\"email\":\"$OTHER_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
OTHER_TOKEN=$(json_get "$BODY" access_token)

call PATCH "/api/carts/me/items/$ITEM_ID" "$OTHER_TOKEN" '{"quantity":99}'
check "他人无法修改我的清单条目 404" "$CODE" "404"

call GET /api/admin/carts "$USER_TOKEN"
check "普通用户访问管理员接口 403" "$CODE" "403"

section "4.5 出游采购组准备（建组 / 邀请码 / 加入 / 上限）"
if [[ -z "$ADMIN_PASSWORD" && -f .env ]]; then
  ADMIN_PASSWORD=$(grep '^BOOTSTRAP_ADMIN_PASSWORD=' .env | cut -d= -f2-)
fi
call POST /api/auth/login "" "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}"
ADMIN_TOKEN=$(json_get "$BODY" access_token)
check "管理员登录 200" "$CODE" "200"

# 把上一段的另一个用户提升为采购员
call GET /api/admin/users "$ADMIN_TOKEN"
check "管理员读取用户列表 200" "$CODE" "200"
OTHER_UID=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(u["id"] for u in d if u["email"]==sys.argv[1]))' "$OTHER_EMAIL" <<<"$BODY")

call PATCH "/api/admin/users/$OTHER_UID/role" "$ADMIN_TOKEN" '{"role":"purchaser"}'
check "提升为采购人 200" "$CODE" "200"
check "角色已变为 purchaser" "$BODY" '"role":"purchaser"'

call POST /api/auth/login "" "{\"email\":\"$OTHER_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
PURCH_TOKEN=$(json_get "$BODY" access_token)
check "采购人登录 200" "$CODE" "200"
check "登录角色为 purchaser" "$BODY" '"role":"purchaser"'

call GET /api/admin/users "$PURCH_TOKEN"
check "采购人不能看用户列表 403" "$CODE" "403"

# 采购员建出游组：标题 + 开始/结束日期，自动生成 4 位邀请码
G0_TITLE="冒烟东京出游组"
call POST /api/groups "$PURCH_TOKEN" "{\"title\":\"$G0_TITLE\",\"start_date\":\"$FUT1\",\"end_date\":\"$FUT2\"}"
check "采购员创建出游组 201" "$CODE" "201"
check "组状态 open" "$BODY" '"status":"open"'
check "组带开始日期" "$BODY" "\"start_date\":\"$FUT1\""
check "组带结束日期" "$BODY" "\"end_date\":\"$FUT2\""
GROUP_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
GROUP_CODE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["invite_code"])' <<<"$BODY")
CODE_DIGITS=$(python3 -c "import re; print('OK' if re.fullmatch(r'\d{4}', '$GROUP_CODE') else 'NO')")
check "生成 4 位数字邀请码" "$CODE_DIGITS" "OK"

# 结束日期早于开始日期 → 422
call POST /api/groups "$PURCH_TOKEN" "{\"title\":\"日期错误组\",\"start_date\":\"$FUT2\",\"end_date\":\"$FUT1\"}"
check "结束日期早于开始日期 422" "$CODE" "422"

# 普通用户不能建组；admin 可看全部；采购员只能看自己的
call POST /api/groups "$USER_TOKEN" "{\"title\":\"越权组\",\"start_date\":\"$FUT1\",\"end_date\":\"$FUT2\"}"
check "普通用户建组被拒 403" "$CODE" "403"
call GET /api/groups "$ADMIN_TOKEN"
check "管理员查看全部组 200" "$CODE" "200"
check "管理列表含新组" "$BODY" "$G0_TITLE"
call GET /api/groups "$PURCH_TOKEN"
check "采购员查看全部组被拒 403" "$CODE" "403"
call GET /api/groups/me "$PURCH_TOKEN"
check "采购员查看自己组 200" "$CODE" "200"
check "自己组标题正确" "$BODY" "$G0_TITLE"

# 需求人凭邀请码加入；重复加入 409；无效码 404；创建者不能加入自己的组
call POST /api/groups/join "$USER_TOKEN" "{\"invite_code\":\"$GROUP_CODE\"}"
check "凭邀请码加入出游组 201" "$CODE" "201"
check "加入后成员数 1" "$BODY" '"member_count":1'
call POST /api/groups/join "$USER_TOKEN" "{\"invite_code\":\"$GROUP_CODE\"}"
check "重复加入被拒 409" "$CODE" "409"
call POST /api/groups/join "$USER_TOKEN" '{"invite_code":"0000"}'
check "无效邀请码 404" "$CODE" "404"
call POST /api/groups/join "$PURCH_TOKEN" "{\"invite_code\":\"$GROUP_CODE\"}"
check "创建者不能加入自己组 400" "$CODE" "400"

# 同一采购员累计最多 3 个组：再造 1 个过去区间组 + 1 个未来组 = 3，第 4 个 400
GX_TITLE="冒烟已到期组"
call POST /api/groups "$PURCH_TOKEN" "{\"title\":\"$GX_TITLE\",\"start_date\":\"$PAST1\",\"end_date\":\"$PAST2\"}"
check "创建过去区间组 201" "$CODE" "201"
GX_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
GX_CODE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["invite_code"])' <<<"$BODY")

G2_TITLE="冒烟二次出游组"
call POST /api/groups "$PURCH_TOKEN" "{\"title\":\"$G2_TITLE\",\"start_date\":\"$FUT1\",\"end_date\":\"$FUT2\"}"
check "创建第二个未来组 201" "$CODE" "201"
G2_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
G2_CODE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["invite_code"])' <<<"$BODY")

call POST /api/groups "$PURCH_TOKEN" "{\"title\":\"第4个超额组\",\"start_date\":\"$FUT1\",\"end_date\":\"$FUT2\"}"
check "累计第 4 个组被拒 400" "$CODE" "400"
check "超限提示明确" "$BODY" "上限"

section "5. 提交与撤回（整单归入出游组）"
# 需求人只在一个进行中组（G0）内 → 提交自动归组
call POST /api/carts/me/submit "$USER_TOKEN"
check "提交返回 200" "$CODE" "200"
check "状态流转为 submitted" "$BODY" '"status":"submitted"'
check "自动归入进行中出游组" "$BODY" "\"title\":\"$G0_TITLE\""
CART_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

call PATCH "/api/carts/me/items/$ITEM_ID" "$USER_TOKEN" '{"quantity":7}'
check "已提交后用户不能再改数量 404" "$CODE" "404"

call POST /api/carts/me/withdraw "$USER_TOKEN"
check "撤回申请返回 200" "$CODE" "200"
check "撤回后回到 draft" "$BODY" '"status":"draft"'
check "撤回后解除组归属" "$BODY" '"group":null'

call PATCH "/api/carts/me/items/$ITEM_ID" "$USER_TOKEN" '{"quantity":6}'
check "撤回后恢复可编辑 200" "$CODE" "200"

call POST /api/carts/me/submit "$USER_TOKEN"
check "重新提交返回 200" "$CODE" "200"
check "再次流转为 submitted" "$BODY" '"status":"submitted"'
check "提交时单价未冻结" "$BODY" '"price_frozen":false'

section "6. 管理员处理采购与采购员勾选"
call GET /api/admin/carts "$ADMIN_TOKEN"
check "管理员读取全部清单 200" "$CODE" "200"
check "能看到刚提交的清单" "$BODY" "$USER_EMAIL"

call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"locked"}'
check "锁定采购返回 200" "$CODE" "200"
check "状态流转为 locked" "$BODY" '"status":"locked"'
check "锁定后单价已冻结" "$BODY" '"price_frozen":true'
check "冻结单价等于商品价" "$BODY" "\"unit_price_cents\":$PROD_PRICE"

call PATCH "/api/admin/cart-items/$ITEM_ID/purchased" "$ADMIN_TOKEN" '{"purchased":true}'
check "管理员标记已采购 200" "$CODE" "200"
check "条目已标记为已采购" "$BODY" '"purchased":true'

call PATCH "/api/admin/cart-items/$ITEM_ID/purchased" "$ADMIN_TOKEN" '{"purchased":false}'
check "管理员取消采购标记 200" "$CODE" "200"
check "条目恢复为未采购" "$BODY" '"purchased":false'

call PATCH "/api/admin/cart-items/$ITEM_ID/purchased" "$USER_TOKEN" '{"purchased":true}'
check "普通用户无法标记已采购 403" "$CODE" "403"

# 采购员只能勾自己创建的组内的条目（ITEM_ID 属于 G0，创建者=采购员 → 200）
call PATCH "/api/admin/cart-items/$ITEM_ID/purchased" "$PURCH_TOKEN" '{"purchased":true}'
check "采购员标记本组条目已采购 200" "$CODE" "200"
check "条目已标记为已采购" "$BODY" '"purchased":true'
call PATCH "/api/admin/cart-items/$ITEM_ID/purchased" "$PURCH_TOKEN" '{"purchased":false}'
check "采购员取消本组采购标记 200" "$CODE" "200"

# 确认采购备忘：采购员可勾（防买重）；需求人只能读，不能改
call PATCH "/api/admin/cart-items/$ITEM_ID/confirmed" "$USER_TOKEN" '{"confirmed":true}'
check "需求人不能勾确认采购 403" "$CODE" "403"
call PATCH "/api/admin/cart-items/$ITEM_ID/confirmed" "$PURCH_TOKEN" '{"confirmed":true}'
check "采购员勾确认采购 200" "$CODE" "200"
check "条目确认采购状态已置真" "$BODY" '"purchase_confirmed":true'
call GET /api/carts/me "$USER_TOKEN"
check "需求人清单接口 200" "$CODE" "200"
CFM=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print("OK" if any(it["id"]==int(sys.argv[1]) and it["purchase_confirmed"] for it in d["items"]) else "NO")' "$ITEM_ID" <<<"$BODY")
check "需求人只读可见确认采购状态" "$CFM" "OK"

# 状态机收口：解锁 -> 非法跳转 -> 重新锁定 -> 失败退回 -> 重开 -> 成功
call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"submitted"}'
check "管理员解锁返回 200" "$CODE" "200"
check "解锁后回到 submitted" "$BODY" '"status":"submitted"'
call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"success"}'
check "非法状态跳转被拒 409" "$CODE" "409"
call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"locked"}'
check "重新锁定返回 200" "$CODE" "200"
call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"failed"}'
check "标记采购失败返回 200" "$CODE" "200"
check "状态流转为 failed" "$BODY" '"status":"failed"'
call POST /api/carts/me/reopen "$USER_TOKEN"
check "失败后用户重新打开 200" "$CODE" "200"
check "重新打开回到 draft" "$BODY" '"status":"draft"'
call POST /api/carts/me/submit "$USER_TOKEN"
check "重开后再次提交 200" "$CODE" "200"
call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"locked"}'
check "再次锁定 200" "$CODE" "200"
call PATCH "/api/admin/carts/$CART_ID/status" "$ADMIN_TOKEN" '{"status":"success"}'
check "确认采购成功 200" "$CODE" "200"
check "状态流转为 success" "$BODY" '"status":"success"'

section "7. 链接解析与商品库"
# 本段依赖对 kakaku.com 的真实网络访问（解析商品详情页 JSON-LD）。
call POST /api/products/parse-url "$USER_TOKEN" '{"url":"https://kakaku.com/item/K0001673419/"}'
check "解析商品链接返回 200" "$CODE" "200"
check "解析结果包含商品名" "$BODY" '"name"'
check "解析结果包含日元价字段" "$BODY" '"price_yen"'

# 商品号前缀字母不限（J/K 等历史前缀均可），见 kakaku.py ITEM_URL_RE
call POST /api/products/parse-url "$USER_TOKEN" '{"url":"https://kakaku.com/item/J0000049821/?lid=20190108pricemenu_hot"}'
check "J前缀商品链接解析 200" "$CODE" "200"
check "J前缀解析结果包含商品名" "$BODY" '"name"'
check "J前缀解析为 SONY 降噪耳机" "$BODY" 'WF-1000XM6'

call POST /api/products/parse-url "$USER_TOKEN" '{"url":"https://evil.com/item/K0001673419/"}'
check "非 kakaku 链接被拒 400" "$CODE" "400"

# 北村相机商品详情解析（kitamuracamera.jp /buy/item/<数字>/）
call POST /api/products/parse-url "$USER_TOKEN" '{"url":"https://www.kitamuracamera.jp/buy/item/2119341166424/"}'
check "北村相机链接解析 200" "$CODE" "200"
check "北村解析包含商品名" "$BODY" '"name"'
check "北村解析来源为 kitamura" "$BODY" '"source":"kitamura"'
check "北村解析出 α6600" "$BODY" 'α6600'
check "北村解析含图片" "$BODY" '"image_url"'

call POST /api/products/parse-url "$USER_TOKEN" '{"url":"https://www.kitamuracamera.jp/buy/"}'
check "北村目录页(非商品)被拒 400" "$CODE" "400"
call POST /api/products/parse-url "$USER_TOKEN" '{"url":"https://evil.net/buy/item/2119341166424/"}'
check "非北村域名被拒 400" "$CODE" "400"

call POST /api/products/parse-url "" '{"url":"https://kakaku.com/item/K0001673419/"}'
check "未登录解析被拒 401" "$CODE" "401"

NEW_URL="https://kakaku.com/item/KSMOKE${STAMP}/"
call POST /api/products "$ADMIN_TOKEN" "{\"name\":\"冒烟测试商品\",\"source_name\":\"kakaku\",\"source_url\":\"$NEW_URL\",\"price_cents\":31480,\"currency\":\"JPY\"}"
check "管理员创建商品返回 201" "$CODE" "201"
check "新商品币种为 JPY" "$BODY" '"currency":"JPY"'
check "新商品价格正确" "$BODY" '"price_cents":31480'
NEW_PROD_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

call POST /api/products "$ADMIN_TOKEN" "{\"name\":\"重复商品\",\"source_name\":\"kakaku\",\"source_url\":\"$NEW_URL\",\"price_cents\":100}"
check "重复 source_url 被拒 409" "$CODE" "409"

call POST /api/products "$USER_TOKEN" '{"name":"越权商品","source_name":"kakaku","price_cents":100}'
check "普通用户创建商品被拒 403" "$CODE" "403"

call PATCH "/api/products/$NEW_PROD_ID" "$ADMIN_TOKEN" '{"price_cents":2500}'
check "管理员改价返回 200" "$CODE" "200"
check "改价后价格更新" "$BODY" '"price_cents":2500'

call PATCH "/api/products/$NEW_PROD_ID" "$USER_TOKEN" '{"price_cents":1}'
check "普通用户改价被拒 403" "$CODE" "403"

call DELETE "/api/products/$PRODUCT_ID" "$ADMIN_TOKEN"
check "删除已被加购的商品被拒 409" "$CODE" "409"

call DELETE "/api/products/$NEW_PROD_ID" "$ADMIN_TOKEN"
check "管理员删除未引用商品 204" "$CODE" "204"

section "7.5 价格算法与设置"
# 备份当前参数，测完恢复，避免覆盖手工改过的汇率/税率。
call GET /api/settings/price "$ADMIN_TOKEN"
check "读取价格参数 200" "$CODE" "200"
check "含税率字段" "$BODY" '"tax_rate"'
check "含汇率字段" "$BODY" '"exchange_rate_jpy_cny"'
ORIG_TAX=$(json_get "$BODY" tax_rate)
ORIG_RATE=$(json_get "$BODY" exchange_rate_jpy_cny)

call PUT /api/settings/price "$USER_TOKEN" '{"tax_rate":5,"exchange_rate_jpy_cny":0.05}'
check "普通用户改参数被拒 403" "$CODE" "403"

call PUT /api/settings/price "$ADMIN_TOKEN" '{"tax_rate":10,"exchange_rate_jpy_cny":0.048}'
check "管理员改参数 200" "$CODE" "200"

# 算法验证：商品原价统一按税前口径，JPY 10000 円，税率 10% → 含税 11000 円，汇率 0.048 → 52800 分。
TAX_URL="https://kakaku.com/item/KTAX${STAMP}/"
call POST /api/products "$ADMIN_TOKEN" "{\"name\":\"算法测试商品\",\"source_name\":\"kakaku\",\"source_url\":\"$TAX_URL\",\"price_cents\":10000,\"currency\":\"JPY\",\"tax_included\":false}"
check "创建税前商品 201" "$CODE" "201"
check "含税价 = 11000" "$BODY" '"taxed_price_cents":11000'
check "人民币等价 = 52800 分" "$BODY" '"price_cny_cents":52800'
TAX_PROD_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

call PATCH "/api/products/$TAX_PROD_ID" "$ADMIN_TOKEN" '{"tax_included":true}'
check "旧税标记字段兼容更新 200" "$CODE" "200"
check "税标记不改变统一含税价算法" "$BODY" '"taxed_price_cents":11000'
check "税标记不改变统一人民币算法 = 52800 分" "$BODY" '"price_cny_cents":52800'

call DELETE "/api/products/$TAX_PROD_ID" "$ADMIN_TOKEN"
check "清理算法测试商品 204" "$CODE" "204"

call PUT /api/settings/price "$ADMIN_TOKEN" "{\"tax_rate\":$ORIG_TAX,\"exchange_rate_jpy_cny\":$ORIG_RATE}"
check "恢复原价格参数 200" "$CODE" "200"

section "7.6 链接加购与手工添加"
MUSER_EMAIL="muser${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$MUSER_EMAIL\",\"full_name\":\"加购测试\",\"password\":\"$USER_PASSWORD\"}"
call POST /api/auth/login "" "{\"email\":\"$MUSER_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
MUSER_TOKEN=$(json_get "$BODY" access_token)
check "加购测试用户登录 200" "$CODE" "200"

call POST /api/carts/me/items/manual "$MUSER_TOKEN" '{"name":"冒烟手工商品","price_yen":8850,"quantity":1}'
check "手工添加返回 201" "$CODE" "201"
check "手工商品来源正确" "$BODY" '"source_name":"手工添加"'
check "手工商品日元价正确" "$BODY" '"unit_price_cents":8850'
check "手工商品币种为 JPY" "$BODY" '"currency":"JPY"'

call POST /api/carts/me/items/by-url "$MUSER_TOKEN" '{"url":"https://kakaku.com/item/K0001673419/","quantity":1}'
check "链接解析加购返回 201" "$CODE" "201"
check "清单中出现 kakaku 来源商品" "$BODY" '"source_name":"kakaku"'

# —— 变体批量手工添加：一次 1 商品（类型/备注/商品级图）+ 多颜色行 ——
call POST /api/carts/me/items/manual-batch "$MUSER_TOKEN" '{"name":"冒烟变色保温杯","price_yen":1980,"category":"日用品","remark":"小红书攻略：xx 店购买","variants":[{"color":"黑色","quantity":2},{"color":"白色","quantity":1}]}'
check "变体批量添加返回 201" "$CODE" "201"
check "变体商品类型透传" "$BODY" '"category":"日用品"'
check "变体商品备注透传" "$BODY" '"remark":"小红书攻略：xx 店购买"'
V1_QTY=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(sum(1 for it in d["items"] if it["product"]["name"]=="冒烟变色保温杯" and it["color"]=="黑色" and it["quantity"]==2))' <<<"$BODY")
V2_QTY=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(sum(1 for it in d["items"] if it["product"]["name"]=="冒烟变色保温杯" and it["color"]=="白色" and it["quantity"]==1))' <<<"$BODY")
check "黑色变体 2 件入单" "$V1_QTY" "1"
check "白色变体 1 件入单" "$V2_QTY" "1"
check "变体条目确认采购默认 false" "$BODY" '"purchase_confirmed":false'
# 同商品多颜色 = 同一 product_id（唯一约束已移除，分组展示的数据基础）
VPID=$(python3 -c 'import json,sys; d=json.load(sys.stdin); ids=[it["product"]["id"] for it in d["items"] if it["product"]["name"]=="冒烟变色保温杯"]; print("OK" if ids and all(i==ids[0] for i in ids) else "DIFF")' <<<"$BODY")
check "多颜色共享同一商品 ID" "$VPID" "OK"

section "8. 出游采购组进阶（批量拉人 / 到期停收 / 多组选择 / 越权 / 完成删除）"

# 8.1 候选用户：采购员/管理员可见，普通用户 403
call GET /api/groups/member-options "$PURCH_TOKEN"
check "采购员查看候选用户 200" "$CODE" "200"
check "候选含普通用户" "$BODY" "加购测试"
call GET /api/groups/member-options "$USER_TOKEN"
check "普通用户不能看候选用户 403" "$CODE" "403"

# 8.2 到期组（结束日期已过）：成员提交 → 422
GM2_EMAIL="expired${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$GM2_EMAIL\",\"full_name\":\"到期成员\",\"password\":\"$USER_PASSWORD\"}"
call POST /api/auth/login "" "{\"email\":\"$GM2_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
GM2_TOKEN=$(json_get "$BODY" access_token)
call GET /api/groups/member-options "$PURCH_TOKEN"
GM2_UID=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(u["id"] for u in d if u["email"]==sys.argv[1]))' "$GM2_EMAIL" <<<"$BODY")
call POST "/api/groups/$GX_ID/members" "$PURCH_TOKEN" "{\"user_ids\":[$GM2_UID]}"
check "采购员拉人入到期组 201" "$CODE" "201"
check "到期组成员数 1" "$BODY" '"member_count":1'
call POST /api/carts/me/items/manual "$GM2_TOKEN" '{"name":"到期组商品","price_yen":1000,"quantity":1}'
check "到期组成员加购 201" "$CODE" "201"
call POST /api/carts/me/submit "$GM2_TOKEN"
check "到期组收单被拒 422" "$CODE" "422"
check "提示先加入进行中组" "$BODY" "进行中的出游采购组"

# 8.3 同属多个进行中组：不选 422，显式选组 200
GM1_EMAIL="multi${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$GM1_EMAIL\",\"full_name\":\"多组用户\",\"password\":\"$USER_PASSWORD\"}"
call POST /api/auth/login "" "{\"email\":\"$GM1_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
GM1_TOKEN=$(json_get "$BODY" access_token)
call GET /api/groups/member-options "$PURCH_TOKEN"
GM1_UID=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(u["id"] for u in d if u["email"]==sys.argv[1]))' "$GM1_EMAIL" <<<"$BODY")
call POST "/api/groups/$G2_ID/members" "$PURCH_TOKEN" "{\"user_ids\":[$GM1_UID]}"
check "拉人入第二组 201" "$CODE" "201"
call POST "/api/groups/$GROUP_ID/members" "$PURCH_TOKEN" "{\"user_ids\":[$GM1_UID]}"
check "同人再入第一组 201" "$CODE" "201"
call POST /api/carts/me/items/manual "$GM1_TOKEN" '{"name":"多组选择商品","price_yen":3300,"quantity":1}'
check "多组成员加购 201" "$CODE" "201"
call POST /api/carts/me/submit "$GM1_TOKEN"
check "多进行中组不选被拒 422" "$CODE" "422"
check "提示需选择组" "$BODY" "请选择要提交给的组"
call POST /api/carts/me/submit "$GM1_TOKEN" "{\"group_id\":$G2_ID}"
check "显式选择提交 200" "$CODE" "200"
check "提交归入所选组" "$BODY" "\"title\":\"$G2_TITLE\""
CART_GM1=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
GM1_ITEM=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["id"])' <<<"$BODY")

# 普通用户无权拉人入组
call POST "/api/groups/$GROUP_ID/members" "$USER_TOKEN" "{\"user_ids\":[$GM1_UID]}"
check "非创建者拉人被拒 403" "$CODE" "403"

# 8.4 跨采购员越权：他组条目 403，本组 200
PUR2_EMAIL="pur2${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$PUR2_EMAIL\",\"full_name\":\"二号采购\",\"password\":\"$USER_PASSWORD\"}"
PUR2_UID=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(u["id"] for u in d if u["email"]==sys.argv[1]))' "$PUR2_EMAIL" <<<"$(request GET /api/admin/users "$ADMIN_TOKEN" | sed '$d')")
call PATCH "/api/admin/users/$PUR2_UID/role" "$ADMIN_TOKEN" '{"role":"purchaser"}'
check "二号采购员提升 200" "$CODE" "200"
call POST /api/auth/login "" "{\"email\":\"$PUR2_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
PUR2_TOKEN=$(json_get "$BODY" access_token)

GP_TITLE="二号采购的组"
call POST /api/groups "$PUR2_TOKEN" "{\"title\":\"$GP_TITLE\",\"start_date\":\"$FUT1\",\"end_date\":\"$FUT2\"}"
check "二号采购员建组 201" "$CODE" "201"
GP_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
GP_CODE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["invite_code"])' <<<"$BODY")

GM3_EMAIL="gmem3${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$GM3_EMAIL\",\"full_name\":\"三号组员\",\"password\":\"$USER_PASSWORD\"}"
call POST /api/auth/login "" "{\"email\":\"$GM3_EMAIL\",\"password\":\"$USER_PASSWORD\"}"
GM3_TOKEN=$(json_get "$BODY" access_token)
call POST /api/groups/join "$GM3_TOKEN" "{\"invite_code\":\"$GP_CODE\"}"
check "三号组员凭码加入 201" "$CODE" "201"
call POST /api/carts/me/items/manual "$GM3_TOKEN" '{"name":"他组商品","price_yen":1500,"quantity":1}'
check "三号组员加购 201" "$CODE" "201"
call POST /api/carts/me/submit "$GM3_TOKEN"
check "三号组员自动归组提交 200" "$CODE" "200"
GM3_ITEM=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["id"])' <<<"$BODY")
CART_GM3=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

call PATCH "/api/admin/cart-items/$GM3_ITEM/purchased" "$PURCH_TOKEN" '{"purchased":true}'
check "一号采购不能标记他组条目 403" "$CODE" "403"
call PATCH "/api/admin/cart-items/$GM3_ITEM/purchased" "$PUR2_TOKEN" '{"purchased":true}'
check "二号采购标记本组条目 200" "$CODE" "200"
call PATCH "/api/admin/cart-items/$GM3_ITEM/confirmed" "$ADMIN_TOKEN" '{"confirmed":true}'
check "管理员可代管任意组确认 200" "$CODE" "200"
check "他组条目确认置真" "$BODY" '"purchase_confirmed":true'

# 管理台聚合视图：全部组 + 组内条目与需求人
call GET /api/groups "$ADMIN_TOKEN"
check "管理员查看全部组 200" "$CODE" "200"
check "聚合含一号组" "$BODY" "$G0_TITLE"
check "聚合含二号采购组" "$BODY" "$GP_TITLE"
check "组内条目带需求人" "$BODY" "三号组员"

# 8.5 完成 / 删除收口
call PATCH "/api/groups/$G2_ID" "$PURCH_TOKEN" '{"status":"completed"}'
check "标记组完成 200" "$CODE" "200"
check "组状态 completed" "$BODY" '"status":"completed"'
call POST /api/groups/join "$GM2_TOKEN" "{\"invite_code\":\"$G2_CODE\"}"
check "已完成组不能加入 400" "$CODE" "400"
call PATCH "/api/groups/$G2_ID" "$PURCH_TOKEN" '{"status":"open"}'
check "已完成组不能重开 400" "$CODE" "400"
call POST "/api/groups/$G2_ID/members" "$PURCH_TOKEN" "{\"user_ids\":[$GM2_UID]}"
check "已完成组不能新增成员 400" "$CODE" "400"
call DELETE "/api/groups/$G2_ID" "$PURCH_TOKEN"
check "有归组清单的组不可删 409" "$CODE" "409"
call DELETE "/api/groups/$GX_ID" "$PURCH_TOKEN"
check "无归组清单的组可删 204" "$CODE" "204"
call DELETE "/api/groups/$GROUP_ID" "$USER_TOKEN"
check "非创建者删除组 403" "$CODE" "403"

# 二号组员收口（锁定 → 成功），避免残留 submitted
call PATCH "/api/admin/carts/$CART_GM1/status" "$ADMIN_TOKEN" '{"status":"locked"}'
check "多组用户清单锁定 200" "$CODE" "200"
call PATCH "/api/admin/carts/$CART_GM1/status" "$ADMIN_TOKEN" '{"status":"success"}'
check "多组用户清单成功 200" "$CODE" "200"
call PATCH "/api/admin/carts/$CART_GM3/status" "$ADMIN_TOKEN" '{"status":"locked"}'
check "他组用户清单锁定 200" "$CODE" "200"
call PATCH "/api/admin/carts/$CART_GM3/status" "$ADMIN_TOKEN" '{"status":"success"}'
check "他组用户清单成功 200" "$CODE" "200"

section "8.55 批次机制（出游开始自动封板 / 组内锁定解锁 / 越权保护）"
# 批次机制：组到达 start_date 后「提交即封板」，每锁定一次为需求人自动开下一批空草稿。
TODAY=$(python3 -c "from datetime import date;print(date.today())")
TOMORROW=$(python3 -c "from datetime import date,timedelta;print(date.today()+timedelta(days=1))")
TODAY_END=$(python3 -c "from datetime import date,timedelta;print(date.today()+timedelta(days=6))")

# 8.55.1 二号采购员再建「明日开始」组；三号组员加入并在开始前提交（未封板，可撤回）
GT_TITLE="今日封板测试组"
call POST /api/groups "$PUR2_TOKEN" "{\"title\":\"$GT_TITLE\",\"start_date\":\"$TOMORROW\",\"end_date\":\"$TODAY_END\"}"
check "二号采购员建明日开始组 201" "$CODE" "201"
GT_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
GT_CODE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["invite_code"])' <<<"$BODY")

call POST /api/groups/join "$GM3_TOKEN" "{\"invite_code\":\"$GT_CODE\"}"
check "三号组员加入明日组 201" "$CODE" "201"
check "明日组成员数 1" "$BODY" '"member_count":1'

call POST /api/carts/me/items/manual "$GM3_TOKEN" '{"name":"封板批次商品","price_yen":2200,"quantity":2}'
check "明日组内加购 201" "$CODE" "201"

call POST /api/carts/me/submit "$GM3_TOKEN" "{\"group_id\":$GT_ID}"
check "未开始组提交 200" "$CODE" "200"
check "未开始提交为 submitted" "$BODY" '"status":"submitted"'
check "未开始批次号 batch_no=1" "$BODY" '"batch_no":1'
check "未开始组 started=false" "$BODY" '"started":false'
check "未开始提交未冻结单价" "$BODY" '"price_frozen":false'
C1_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

# 采购员把开始日期改为今天 → 组进入采购期
call PATCH "/api/groups/$GT_ID" "$PUR2_TOKEN" "{\"start_date\":\"$TODAY\"}"
check "采购员把开始日期改为今天 200" "$CODE" "200"
check "开始日期已更新" "$BODY" "\"start_date\":\"$TODAY\""

# 已开始组内的 submitted 批次不可自行撤回 → 409
call POST /api/carts/me/withdraw "$GM3_TOKEN"
check "已开始组撤回被拒 409" "$CODE" "409"
check "提示批次已封板" "$BODY" "封板"

# 8.55.2 组级入口：采购员锁定组内 submitted 批次（submitted->locked）
call PATCH "/api/groups/$GT_ID/carts/$C1_ID/status" "$PUR2_TOKEN" '{"status":"locked"}'
check "组内锁定 submitted 批次 200" "$CODE" "200"
check "组内锁定后状态 locked" "$BODY" '"status":"locked"'
check "组内锁定保持 batch_no=1" "$BODY" '"batch_no":1'
check "组内锁定冻结单价" "$BODY" '"price_frozen":true'

# 8.55.3 出游开始后用户提交即自动封板 → 第 2 批，并自动开一张空草稿
call POST /api/carts/me/items/manual "$GM3_TOKEN" '{"name":"第二批商品","price_yen":1100,"quantity":1}'
check "第二批加购 201" "$CODE" "201"
call POST /api/carts/me/submit "$GM3_TOKEN" "{\"group_id\":$GT_ID}"
check "已开始组提交即封板 200" "$CODE" "200"
check "第二批自动锁定" "$BODY" '"status":"locked"'
check "第二批批次号 batch_no=2" "$BODY" '"batch_no":2'
check "第二批单价冻结" "$BODY" '"price_frozen":true'
check "封板组 started=true" "$BODY" '"started":true'
C2_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

call GET /api/carts/me "$GM3_TOKEN"
check "封板后自动下一批草稿 200" "$CODE" "200"
check "下一批草稿为空" "$BODY" '"items":[]'
check "下一批草稿 batch_no=0" "$BODY" '"batch_no":0'
check "下一批草稿未归组" "$BODY" '"group":null'
DRAFT2_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

# 8.55.3b 批次列表 + 按 id 只读查看 + 指定 cart_id 加购校验
call GET /api/carts/me/batches "$GM3_TOKEN"
check "批次列表 200" "$CODE" "200"
BATCH_LIST_OK=$(python3 - <<PY
import json
rows = json.loads('''$BODY''')
ids = {r["id"] for r in rows}
st = {r["id"]: r["status"] for r in rows}
bn = {r["id"]: r["batch_no"] for r in rows}
ok = (int('$C1_ID') in ids and int('$C2_ID') in ids and int('$DRAFT2_ID') in ids
      and st[int('$C1_ID')] == "locked" and st[int('$C2_ID')] == "locked"
      and st[int('$DRAFT2_ID')] == "draft" and bn[int('$DRAFT2_ID')] == 0)
print("OK" if ok else "NO:" + str([(r["id"], r["batch_no"], r["status"], r["count"]) for r in rows]))
PY
)
check "批次列表含第1/2批 locked + 新草稿" "$BATCH_LIST_OK" "OK"

call GET "/api/carts/me/$C1_ID" "$GM3_TOKEN"
check "按 id 查看已锁定第1批 200" "$CODE" "200"
check "锁定批仍可见条目" "$BODY" '"status":"locked"'
check "锁定批商品未消失" "$BODY" "封板批次商品"

call GET "/api/carts/me/$C2_ID" "$GM3_TOKEN"
check "按 id 查看已锁定第2批 200" "$CODE" "200"
check "第2批商品仍在" "$BODY" "第二批商品"

call POST /api/carts/me/items/manual "$GM3_TOKEN" "{\"name\":\"不应写入锁定批\",\"price_yen\":100,\"quantity\":1,\"cart_id\":$C1_ID}"
check "指定锁定批次加购被拒 409" "$CODE" "409"

call POST /api/carts/me/items/manual "$GM3_TOKEN" "{\"name\":\"写入新草稿\",\"price_yen\":330,\"quantity\":1,\"cart_id\":$DRAFT2_ID}"
check "指定新草稿加购 201" "$CODE" "201"
check "加购落在新草稿" "$BODY" "写入新草稿"
check "加购目标仍是草稿" "$BODY" '"status":"draft"'
# 必须删掉测试条目：非空草稿不会被 prune_empty_drafts 回收，解锁后 /carts/me 会拿到 DRAFT2 而非第2批
DRAFT2_ITEM=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(it["id"] for it in d["items"] if it["product"]["name"]=="写入新草稿"))' <<<"$BODY")
call DELETE "/api/carts/me/items/$DRAFT2_ITEM" "$GM3_TOKEN"
check "清掉新草稿测试条目 204" "$CODE" "204"

# 8.55.4 组详情聚合两个已封板批次（第1批 locked + 第2批 locked），条目带批次标记
call GET /api/groups/me "$PUR2_TOKEN"
check "二号采购工作台组列表 200" "$CODE" "200"
BATCH_OK=$(python3 - <<PY
import json
data = json.loads('''$BODY''')
g = next(x for x in data if x.get("id") == int('$GT_ID'))
locked = sorted(b["batch_no"] for b in g.get("batches", []) if b.get("status") == "locked")
print("OK" if locked == [1, 2] else "NO:" + str(locked))
PY
)
check "今日组聚合含第1/2批 locked" "$BATCH_OK" "OK"
ITM_OK=$(python3 - <<PY
import json
data = json.loads('''$BODY''')
g = next(x for x in data if x.get("id") == int('$GT_ID'))
it = [i for i in g.get("items", []) if i.get("batch_no") == 2 and i.get("cart_status") == "locked"]
print("OK" if len(it) == 1 else "NO:" + str(len(it)))
PY
)
check "条目级带 batch_no/cart_status" "$ITM_OK" "OK"

# 8.55.5 组内解锁（locked->draft）：恢复可编辑并清理更新的空草稿
call PATCH "/api/groups/$GT_ID/carts/$C2_ID/status" "$PUR2_TOKEN" '{"status":"draft"}'
check "组内解锁第2批 200" "$CODE" "200"
check "解锁后回到 draft" "$BODY" '"status":"draft"'
check "解锁保留批次号 batch_no=2" "$BODY" '"batch_no":2'
check "解锁后解除价格冻结" "$BODY" '"price_frozen":false'

call GET /api/carts/me "$GM3_TOKEN"
check "解锁后当前草稿即第2批 200" "$CODE" "200"
check "解锁后批次号 batch_no=2 可编辑" "$BODY" '"batch_no":2'
check "解锁后第2批商品仍在" "$BODY" "第二批商品"
call GET "/api/carts/me/$C2_ID" "$GM3_TOKEN"
check "按 id 切回解锁批 200" "$CODE" "200"
check "解锁批内容未消失" "$BODY" "第二批商品"
check "解锁批状态 draft" "$BODY" '"status":"draft"'
GT_ITEM=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["id"])' <<<"$BODY")
call PATCH "/api/carts/me/items/$GT_ITEM" "$GM3_TOKEN" '{"quantity":5}'
check "解锁后可修改数量 200" "$CODE" "200"
check "数量已改为 5" "$BODY" '"quantity":5'

call POST /api/carts/me/submit "$GM3_TOKEN" "{\"group_id\":$GT_ID}"
check "解锁后重新提交 200" "$CODE" "200"
check "重提再次自动封板" "$BODY" '"status":"locked"'
check "重提保持 batch_no=2" "$BODY" '"batch_no":2'

# 8.55.6 组内入口的权限与状态机护栏
call PATCH "/api/groups/$GT_ID/carts/$C1_ID/status" "$PURCH_TOKEN" '{"status":"draft"}'
check "跨采购员不能解锁他组批次 403" "$CODE" "403"
call PATCH "/api/groups/$GT_ID/carts/$C2_ID/status" "$GM3_TOKEN" '{"status":"draft"}'
check "需求人不能自行解锁 403" "$CODE" "403"
call PATCH "/api/groups/$GT_ID/carts/$C1_ID/status" "$PUR2_TOKEN" '{"status":"success"}'
check "组内入口不允许跳 success 409" "$CODE" "409"
call PATCH "/api/groups/$GP_ID/carts/$C2_ID/status" "$PUR2_TOKEN" '{"status":"draft"}'
check "他组清单不能跨组解锁 404" "$CODE" "404"
call PATCH "/api/groups/$G2_ID/carts/$CART_GM1/status" "$PURCH_TOKEN" '{"status":"locked"}'
check "已完成组不能变更批次状态 409" "$CODE" "409"
call PATCH "/api/groups/$GT_ID/carts/$C1_ID/status" "$ADMIN_TOKEN" '{"status":"draft"}'
check "管理员可代管解锁任意组批次 200" "$CODE" "200"
check "管理员解锁后回到 draft" "$BODY" '"status":"draft"'

# 收口：一号组标记完成（G0 内有归组清单，不能删但可完成）
call PATCH "/api/groups/$GROUP_ID" "$PURCH_TOKEN" '{"status":"completed"}'
check "一号组标记完成 200" "$CODE" "200"

section "8.6 用户管理 / 价格算法分组 / 注册开关"
# 管理员创建价格组与账号
call POST /api/settings/price-groups "$ADMIN_TOKEN" '{"name":"冒烟海外组","tax_rate":10,"exchange_rate_jpy_cny":0.05}'
check "创建价格分组 201" "$CODE" "201"
check "新分组非默认" "$BODY" '"is_default":false'
GID1=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

U1_EMAIL="mgmt${STAMP}@example.com"
call POST /api/admin/users "$ADMIN_TOKEN" "{\"email\":\"$U1_EMAIL\",\"full_name\":\"托管用户\",\"password\":\"Manage12345\",\"role\":\"user\"}"
check "管理员创建用户 201" "$CODE" "201"
check "新用户默认归属默认组" "$BODY" '"price_group_name":"默认组"'
U1_UID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")

call POST /api/admin/users "$USER_TOKEN" "{\"email\":\"x${STAMP}@example.com\",\"full_name\":\"越权\",\"password\":\"Manage12345\"}"
check "普通用户不能建号 403" "$CODE" "403"

call PATCH "/api/admin/users/$U1_UID/password" "$ADMIN_TOKEN" '{"password":"NewPass98765"}'
check "管理员重置密码 200" "$CODE" "200"
call POST /api/auth/login "" "{\"email\":\"$U1_EMAIL\",\"password\":\"NewPass98765\"}"
U1_TOKEN=$(json_get "$BODY" access_token)
check "新密码可登录 200" "$CODE" "200"
call POST /api/auth/login "" "{\"email\":\"$U1_EMAIL\",\"password\":\"Manage12345\"}"
check "旧密码已失效 401" "$CODE" "401"

call PATCH "/api/admin/users/$U1_UID/price-group" "$ADMIN_TOKEN" "{\"price_group_id\":$GID1}"
check "设置用户归属组 200" "$CODE" "200"
check "归属组已更新" "$BODY" "\"price_group_id\":$GID1"

call POST /api/carts/me/items/manual "$U1_TOKEN" '{"name":"分组验算商品","price_yen":1000,"quantity":1}'
check "分组用户手工加购 201" "$CODE" "201"
check "按海外组 0.05 汇率折算(含税1100円=5500分)" "$BODY" '"price_cny_cents":5500'

# 有成员的分组不可删；清空归属后可删
call DELETE "/api/settings/price-groups/$GID1" "$ADMIN_TOKEN"
check "有成员的分组拒绝删除 400" "$CODE" "400"
call PATCH "/api/admin/users/$U1_UID/price-group" "$ADMIN_TOKEN" '{"price_group_id":null}'
check "清空用户归属组 200" "$CODE" "200"
call DELETE "/api/settings/price-groups/$GID1" "$ADMIN_TOKEN"
check "无成员分组可删除 200" "$CODE" "200"
check "删除分组返回 ok" "$BODY" '"ok":true'

# 删除语义（v0.2 起）：彻底删除账号与全部清单；被删账号登录 401
call DELETE "/api/admin/users/$U1_UID" "$ADMIN_TOKEN"
check "删除有记录用户彻底删除 200" "$CODE" "200"
check "返回 action=deleted" "$BODY" '"action":"deleted"'
call POST /api/auth/login "" "{\"email\":\"$U1_EMAIL\",\"password\":\"NewPass98765\"}"
check "被删账号登录被拒 401" "$CODE" "401"

# 无记录用户可物理删除；不能删除自己
U2_EMAIL="fresh${STAMP}@example.com"
call POST /api/admin/users "$ADMIN_TOKEN" "{\"email\":\"$U2_EMAIL\",\"full_name\":\"新面孔\",\"password\":\"Fresh12345\"}"
U2_UID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$BODY")
call DELETE "/api/admin/users/$U2_UID" "$ADMIN_TOKEN"
check "无记录用户物理删除 200" "$CODE" "200"
check "返回 action=deleted" "$BODY" '"action":"deleted"'
ADMIN_ID=$(python3 -c 'import json,sys; print(next(u["id"] for u in json.load(sys.stdin) if u["role"]=="admin"))' <<<"$(request GET /api/admin/users "$ADMIN_TOKEN" | sed '$d')")
call DELETE "/api/admin/users/$ADMIN_ID" "$ADMIN_TOKEN"
check "不能删除自己 400" "$CODE" "400"

# 注册开关
call GET /api/settings/registration ""
check "注册开关公开可读 200" "$CODE" "200"
call PUT /api/settings/registration "$ADMIN_TOKEN" '{"allow_registration":false}'
check "关闭自助注册 200" "$CODE" "200"
REG_EMAIL="reg${STAMP}@example.com"
call POST /api/auth/register "" "{\"email\":\"$REG_EMAIL\",\"full_name\":\"注册测试\",\"password\":\"Register12345\"}"
check "关闭后注册被拒 403" "$CODE" "403"
call PUT /api/settings/registration "$ADMIN_TOKEN" '{"allow_registration":true}'
check "恢复自助注册 200" "$CODE" "200"
call POST /api/auth/register "" "{\"email\":\"$REG_EMAIL\",\"full_name\":\"注册测试\",\"password\":\"Register12345\"}"
check "恢复后注册成功 201" "$CODE" "201"

section "9. 静态页面"
FRONTEND="${FRONTEND_BASE:-http://localhost:8080}"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$FRONTEND/")
check "用户页可访问" "$code" "200"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$FRONTEND/admin.html")
check "管理员页可访问" "$code" "200"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$FRONTEND/purchaser.html")
check "采购人页可访问" "$code" "200"

printf '\n\033[1m结果：\033[0m \033[32m%d 通过\033[0m，' "$PASS"
if [[ $FAIL -gt 0 ]]; then printf '\033[31m%d 失败\033[0m\n' "$FAIL"; else printf '\033[32m0 失败\033[0m\n'; fi
[[ $FAIL -eq 0 ]] || exit 1
