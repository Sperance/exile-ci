#!/usr/bin/env bash
# Подпись релизных пакетов ключом релиза в отдельном job'е без кода игры (client.yml, job `sign`): сборка идёт без секретов с
# одноразовым ключом (ci/build-keystore.sh), здесь его подпись снимается, а APK и AAB подписываются настоящим ключом и проверяются.
#   ci/sign.sh apk <вход.apk> <выход.apk>   zipalign + apksigner sign (v1-v3), apksigner verify
#   ci/sign.sh aab <вход.aab> <выход.aab>   jarsigner, jarsigner -verify
# Затем сверяется отпечаток сертификата подписи с сертификатом хранилища: чужая подпись - красный шаг.
# Окружение: RELEASE_KEYSTORE_PATH (файл, ci/keystore.sh), RELEASE_KEYSTORE_PASSWORD, RELEASE_KEY_ALIAS, RELEASE_KEY_PASSWORD;
# пароли передаются инструментам именем переменной (env:), в командной строке их нет.
set -euo pipefail

kind=${1:?usage: sign.sh apk|aab <in> <out>}
in=${2:?input}
out=${3:?output}
: "${RELEASE_KEYSTORE_PATH:?}" "${RELEASE_KEYSTORE_PASSWORD:?}" "${RELEASE_KEY_ALIAS:?}" "${RELEASE_KEY_PASSWORD:?}"
[[ -f $in ]] || { echo "::error::nothing to sign: $in"; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$(dirname "$out")"

expected=$(keytool -list -v -keystore "$RELEASE_KEYSTORE_PATH" -storepass:env RELEASE_KEYSTORE_PASSWORD -alias "$RELEASE_KEY_ALIAS" \
    | sed -n 's/.*SHA256: *//p' | tr -d ':' | tr 'A-F' 'a-f' | head -1)
[[ $expected =~ ^[0-9a-f]{64}$ ]] || { echo "::error::release certificate fingerprint not found in the keystore"; exit 1; }

strip_signature() {
    cp "$in" "$work/stripped.zip"
    local -a old=()
    mapfile -t old < <(unzip -Z1 "$work/stripped.zip" | grep -E '^META-INF/([^/]+\.(SF|RSA|DSA|EC)|MANIFEST\.MF)$' || true)
    ((${#old[@]} == 0)) || zip -q -d "$work/stripped.zip" "${old[@]}"
}

case $kind in
    apk)
        tools=$(ls -d "${ANDROID_HOME:?}"/build-tools/* | sort -V | tail -1)
        strip_signature
        "$tools/zipalign" -f -p 4 "$work/stripped.zip" "$work/aligned.apk"
        "$tools/apksigner" sign --ks "$RELEASE_KEYSTORE_PATH" --ks-key-alias "$RELEASE_KEY_ALIAS" \
            --ks-pass env:RELEASE_KEYSTORE_PASSWORD --key-pass env:RELEASE_KEY_PASSWORD --out "$out" "$work/aligned.apk"
        "$tools/apksigner" verify --print-certs "$out" >"$work/certs.txt"
        grep -q '^Number of signers: 1$' "$work/certs.txt" || { echo "::error::$out has not exactly one signer"; exit 1; }
        grep -qi "SHA-256 digest: $expected" "$work/certs.txt" || { echo "::error::$out is not signed with the release key"; exit 1; } ;;
    aab)
        strip_signature
        jarsigner -keystore "$RELEASE_KEYSTORE_PATH" -storepass:env RELEASE_KEYSTORE_PASSWORD -keypass:env RELEASE_KEY_PASSWORD \
            -signedjar "$out" "$work/stripped.zip" "$RELEASE_KEY_ALIAS" >/dev/null
        jarsigner -verify "$out" >"$work/verify.txt" 2>&1 || { echo "::error::$out failed jarsigner -verify"; exit 1; }
        grep -q '^jar verified' "$work/verify.txt" || { echo "::error::$out is not verified"; exit 1; }
        keytool -printcert -jarfile "$out" | sed -n 's/.*SHA256: *//p' | tr -d ':' | tr 'A-F' 'a-f' | grep -qx "$expected" \
            || { echo "::error::$out is not signed with the release key"; exit 1; } ;;
    *) echo "::error::unknown kind '$kind'"; exit 1 ;;
esac
echo "$kind signed with the release key: $(basename "$out")"
