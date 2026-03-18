#!/usr/bin/env bash
set -euo pipefail

# ========= Config =========
OWNER="${OWNER:-<OWNER>}"
REPO="${REPO:-<REPO>}"
APP_NAME="CoinPriceBar"
VOLUME_NAME="CoinPriceBar"

# 由 CI 写入（构建时替换）
SHA256_ARM64="__SHA256_ARM64__"
SHA256_X64="__SHA256_X64__"

# 可选：固定版本标签（如：TAG=v1.0.3）。若不传，脚本将自动解析 latest 的跳转以得到具体版本
TAG="${TAG:-}"

# ==== 默认镜像（可用 MIRRORS 覆盖或追加，空格分隔）====
DEFAULT_MIRRORS=(
  "https://gh-proxy.com"
  "https://ghproxy.net"
)

say() { local zh="$1"; local en="$2"; printf "%s\n%s\n" "$zh" "$en"; }
info(){ say "ℹ️  $1" "ℹ️  $2"; }
ok()  { say "✅ $1" "✅ $2"; }
err() { say "❌ $1" "❌ $2" >&2; }

# ========= 架构与 SHA =========
arch="$(uname -m)"
case "$arch" in
  arm64)  suffix="darwin-arm64"; expect_sha="$SHA256_ARM64" ;;
  x86_64) suffix="darwin-x64";   expect_sha="$SHA256_X64"   ;;
  *) err "不支持的架构：$arch" "Unsupported architecture: $arch"; exit 1 ;;
esac

asset="${APP_NAME}-${suffix}.dmg"

# ========= 解析具体版本（若未显式传 TAG）=========
resolve_tag() {
  # 通过 latest 的最终跳转获取具体 tag：…/releases/download/<TAG>/<asset>
  local latest="https://github.com/${OWNER}/${REPO}/releases/latest/download/${asset}"
  # 仅解析 URL，不下载实体
  local final
  if ! final="$(curl -sIL -o /dev/null -w '%{url_effective}' "$latest")"; then
    return 1
  fi
  # 提取 TAG
  if [[ "$final" =~ /download/([^/]+)/${asset}$ ]]; then
    printf "%s" "${BASH_REMATCH[1]}"
  else
    return 1
  fi
}

if [[ -z "${TAG}" ]]; then
  info "正在解析最新版本标签…" "Resolving the latest tag…"
  if ! TAG="$(resolve_tag)"; then
    err "无法解析最新版本，请稍后重试或手动指定 TAG=..." \
        "Failed to resolve latest tag. Retry later or specify TAG=..."
    exit 1
  fi
fi
ok "已锁定版本：${TAG}" "Pinned version: ${TAG}"

# ========= 构造正式 URL（固定到具体版本）=========
origin_url="https://github.com/${OWNER}/${REPO}/releases/download/${TAG}/${asset}"

# ========= 组装候选 URL 列表 =========
# 顺序：自定义镜像（MIRRORS） > 默认镜像 > 官方源
MIRRORS="${MIRRORS:-}"
declare -a candidates
if [[ -n "$MIRRORS" ]]; then
  for m in $MIRRORS; do candidates+=("${m}/${origin_url}"); done
fi
for m in "${DEFAULT_MIRRORS[@]}"; do candidates+=("${m}/${origin_url}"); done
# 官方源（无镜像）
candidates+=("${origin_url}")

say "已检测架构：${arch} → ${suffix}" "Detected architecture: ${arch} → ${suffix}"
say "目标文件：${asset}" "Target asset: ${asset}"
say "候选下载数：${#candidates[@]}" "Candidates: ${#candidates[@]}"

# ========= 临时目录与清理 =========
tmpd="$(mktemp -d)"
mount_dev=""
cleanup() {
  if [[ -n "$mount_dev" ]]; then hdiutil detach "$mount_dev" -quiet || true; fi
  rm -rf "$tmpd" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cd "$tmpd"

# ========= 并行测速：Range 0–0，计算“连接+首字节”开销，择优 =========
# 为避免部分镜像不支持 HEAD，这里采用 range 0-0 的最小字节请求
probe_best() {
  local -n arr=$1
  local -A score=()           # url -> cost(ms)
  local procs=()
  local i=0 u

  for u in "${arr[@]}"; do
    {
      # 超时：连接 5s，总 8s；失败用一个大数表示
      local out
      if out="$(curl -sS -L -r 0-0 --connect-timeout 5 --max-time 8 -o /dev/null \
                 -w '%{time_connect} %{time_starttransfer}' "$u" 2>/dev/null)"; then
        # 取连接 + 首字节时间之和（秒 -> 毫秒）
        local tc ts; read -r tc ts <<<"$out"
        # bash 浮点：用 awk 转毫秒
        local ms; ms="$(awk -v a="$tc" -v b="$ts" 'BEGIN{printf("%.0f",(a+b)*1000)}')"
        printf "%s %s\n" "$ms" "$u"
      else
        printf "999999 %s\n" "$u"
      fi
    } >"probe.$i" &
    procs+=($!)
    ((i++))
  done

  # 等待
  for p in "${procs[@]}"; do wait "$p" || true; done

  # 选择最小
  local best_ms=999999 best_url=""
  for f in probe.*; do
    read -r ms url <"$f" || continue
    [[ "$ms" =~ ^[0-9]+$ ]] || continue
    if (( ms < best_ms )); then best_ms="$ms"; best_url="$url"; fi
  done

  if [[ -n "$best_url" ]]; then
    echo "$best_url"
  else
    echo ""
  fi
}

best_url="$(probe_best candidates)"
if [[ -z "$best_url" ]]; then
  err "测速失败，改用顺序下载" "Probing failed. Falling back to sequential download"
  best_url="${candidates[0]}"
fi
info "首选通道：$best_url" "Chosen endpoint: $best_url"

# ========= 下载：首选通道失败则依次回退 =========
download_with_fallback() {
  local out="$1"
  shift
  for u in "$@"; do
    info "尝试下载：$u" "Trying: $u"
    if curl -fL --retry 2 --connect-timeout 10 --max-time 600 -o "$out" "$u"; then
      return 0
    fi
    say "此通道不可用，继续回退…" "This endpoint failed. Trying next…"
  done
  return 1
}

# 重新排列候选列表：把 best_url 放到最前
declare -a ordered
ordered=("$best_url")
for u in "${candidates[@]}"; do
  [[ "$u" == "$best_url" ]] || ordered+=("$u")
done

if ! download_with_fallback "$asset" "${ordered[@]}"; then
  err "所有镜像与官方源下载失败" "Failed to download from all endpoints"
  exit 1
fi
ok "已下载 DMG" "DMG downloaded"

# ========= SHA256 校验 =========
if [[ -z "$expect_sha" || "$expect_sha" == "__SHA256_ARM64__" || "$expect_sha" == "__SHA256_X64__" ]]; then
  err "脚本内未注入有效的 SHA256，请更新到最新安装脚本" \
      "Invalid embedded SHA256. Please use the latest installer script."
  exit 1
fi

calc_sha="$(shasum -a 256 "$asset" | awk '{print $1}')"
if [[ "${calc_sha,,}" != "${expect_sha,,}" ]]; then
  err "文件校验失败！期望：$expect_sha，实际：$calc_sha" \
      "Checksum mismatch! Expected: $expect_sha, Got: $calc_sha"
  exit 1
fi
ok "校验通过" "Checksum OK"

# ========= 挂载 & 拷贝 =========
info "挂载 DMG..." "Mounting DMG..."
mount_dev="$(hdiutil attach "$asset" -nobrowse -quiet | awk 'NR==1 {print $1}')"

vol="/Volumes/${VOLUME_NAME}"
if [[ ! -d "$vol" ]]; then
  vol="$(ls /Volumes | grep -i "${VOLUME_NAME}" | head -n1 | sed 's#^#/Volumes/#')"
fi
if [[ -z "${vol:-}" || ! -d "$vol" ]]; then
  err "找不到挂载卷" "Cannot find mounted volume"
  exit 1
fi

info "复制应用到 /Applications..." "Copying app to /Applications..."
cp -R "${vol}/${APP_NAME}.app" /Applications/

info "卸载 DMG..." "Detaching DMG..."
hdiutil detach "$mount_dev" -quiet || true
mount_dev=""

ok "安装完成：/Applications/${APP_NAME}.app" \
   "Installed: /Applications/${APP_NAME}.app"

say "若首次启动被拦截，请到 系统设置 → 隐私与安全性 → 仍要打开, 快速跳转命令：open \"x-apple.systempreferences:com.apple.preference.security\"，点击『仍要打开』" \
    "If blocked on first launch: System Settings → Privacy & Security → Open Anyway, fast skip run: open \"x-apple.systempreferences:com.apple.preference.security\" and click 'Open Anyway'"