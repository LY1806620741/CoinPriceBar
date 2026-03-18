#!/usr/bin/env bash
set -euo pipefail

# ========= Config =========
OWNER="${OWNER:-<OWNER>}"
REPO="${REPO:-<REPO>}"
APP_NAME="CoinPriceBar"
VOLUME_NAME="CoinPriceBar"

# 由 CI 写入
SHA256_ARM64="__SHA256_ARM64__"
SHA256_X64="__SHA256_X64__"

# ==== 镜像====
DEFAULT_MIRRORS=(
  "https://ghproxy.com"
  "https://ghproxy.net"
)

say() { local zh="$1"; local en="$2"; printf "%s\n%s\n" "$zh" "$en"; }
info(){ say "ℹ️  $1" "ℹ️  $2"; }
ok()  { say "✅ $1" "✅ $2"; }
err() { say "❌ $1" "❌ $2" >&2; }

arch="$(uname -m)"
case "$arch" in
  arm64)  suffix="darwin-arm64"; expect_sha="$SHA256_ARM64" ;;
  x86_64) suffix="darwin-x64";   expect_sha="$SHA256_X64"   ;;
  *) err "不支持的架构：$arch" "Unsupported architecture: $arch"; exit 1 ;;
esac

asset="${APP_NAME}-${suffix}.dmg"
base="https://github.com/${OWNER}/${REPO}/releases/latest/download"
origin_url="${base}/${asset}"

MIRRORS="${MIRRORS:-}"
declare -a urls
if [[ -n "$MIRRORS" ]]; then
  for m in $MIRRORS; do urls+=("${m}/${origin_url}"); done
fi
for m in "${DEFAULT_MIRRORS[@]}"; do urls+=("${m}/${origin_url}"); done
urls+=("${origin_url}") # 回退官方

say "已检测架构：${arch} → ${suffix}" "Detected architecture: ${arch} → ${suffix}"
say "目标文件：${asset}" "Target asset: ${asset}"

tmpd="$(mktemp -d)"
mount_dev=""
cleanup(){ [[ -n "$mount_dev" ]] && hdiutil detach "$mount_dev" -quiet || true; rm -rf "$tmpd" || true; }
trap cleanup EXIT
cd "$tmpd"

download() { local url="$1" out="$2"; info "尝试下载：$url" "Trying: $url"; curl -fL --retry 2 --connect-timeout 10 --max-time 600 -o "$out" "$url"; }

dl_ok=false
for u in "${urls[@]}"; do
  if download "$u" "$asset"; then dl_ok=true; break; fi
done
if [[ "$dl_ok" != true ]]; then
  err "所有镜像与官方源下载失败" "Failed to download from mirrors and origin"
  exit 1
fi
ok "已下载 DMG" "DMG downloaded"

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

say "如果首次启动被拦截，请到 系统设置 → 隐私与安全性 → 仍要打开" \
    "If blocked on first launch: System Settings → Privacy & Security → Open Anyway"