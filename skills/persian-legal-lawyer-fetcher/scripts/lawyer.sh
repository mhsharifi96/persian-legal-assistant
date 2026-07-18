#!/usr/bin/env bash

set -Eeuo pipefail

API_URL="https://search-hamivakil.ir/App/Handler/Lawyer.ashx?Method=mGetLawyerData"

# Session ID may expire. Replace it when necessary:
SESSION_ID="${SESSION_ID:-ldrndrkfnf3h4y4h3rfrc1ov}"

OUTPUT_DIR="${OUTPUT_DIR:-lawyers}"
DELAY_SECONDS="${DELAY_SECONDS:-1}"

mkdir -p "$OUTPUT_DIR"

BARS=(
  "34f020263a07438fb9d1c2428bb04c82|آذربایجان شرقی"
  "bab0e39c9a5d4f05b3a1fe9669d8679b|آذربایجان غربی"
  "7ce10c0821a2432296a1f5a5da9e65ba|اردبیل"
  "f9dd45cd90eb44cd9020e2ec205144b1|اصفهان"
  "331BFE0D0C8C4DC59254BA7C8D4D9682|البرز"
  "B51F7B56363143B48BEBAEB3CA66429B|ایلام"
  "f29f18b8f1794ff9a726f682269c4770|بوشهر"
  "EC6CE57684AB4C138D81F31FEEA6AA1C|چهارمحال وبختیاری"
  "21662a8b4b454154b8d31c23a3e74916|خراسان"
  "4b12375a60c24f2da88ad79fdf528184|خراسان جنوبی"
  "5DF507A9D06E4071A8742D1C40095B0C|خراسان شمالی"
  "b16aace987fe41dfb1dd54f09279e5b5|خوزستان"
  "c0abc18f2d254fb3a76b825c1929eb1d|زنجان"
  "67a631bd39b949d8bd6ebbc0ad825b92|سمنان"
  "3b1d33d47a634f02bab272d7816c4466|فارس وکهگیلویه وبویراحمد"
  "c0ff27cc1e424171a5759a9b2a405388|قزوین"
  "bfda2a4d61fb4052a2ea76af82245634|قم"
  "163163ca2cc94a229989ceea75e762f4|گلستان"
  "a8c1cab4bac34107a8635e1a123b6171|گیلان"
  "f74a5ed959cb417abc0151e2e58bf5ed|لرستان"
  "7284c6a564dc4ca8a529250733ccc908|مازندران"
  "c6c8b90e7a6044869b477893d85dc733|مرکز"
  "5aa698052a6b41b6af70dc0529f74a4c|مرکزی (اراک)"
  "9ed990978c3049f6814bf30965cb4059|هرمزگان"
  "099a7c8b861649e9822c1cd03131d80b|همدان"
  "7061a49efa0146239936453832807140|کردستان"
  "d6564942e1c14e2ea33bd2e52c99d686|کرمان"
  "88f665a43d864063a2d2f4af620e08b5|کرمانشاه"
  "2802097CCE4E45979D9348558BC6A871|یزد"
)

for entry in "${BARS[@]}"; do
  IFS='|' read -r bar_id bar_name <<< "$entry"

  output_file="${OUTPUT_DIR}/${bar_id}.json"
  temp_file="${output_file}.tmp"

  payload=$(printf \
    '{"license":"","name":"","family":"","nat":"","mob":"","oftel":"","Bar":"%s","add":"","deg":"","pay":""}' \
    "$bar_id"
  )

  echo "Downloading: ${bar_name}"
  echo "Bar ID:      ${bar_id}"

  http_status=$(
    curl --silent \
      --show-error \
      --location \
      --retry 3 \
      --retry-delay 3 \
      --connect-timeout 30 \
      --max-time 180 \
      --output "$temp_file" \
      --write-out "%{http_code}" \
      "$API_URL" \
      -H 'accept: application/json, text/javascript, */*; q=0.01' \
      -H 'accept-language: en-GB,en;q=0.9,fa-IR;q=0.8,fa;q=0.7,en-US;q=0.6' \
      -H 'cache-control: no-cache' \
      -H 'content-type: application/json;charset=UTF-8' \
      -H 'origin: https://search-hamivakil.ir' \
      -H 'pragma: no-cache' \
      -H 'referer: https://search-hamivakil.ir/' \
      -H 'x-requested-with: XMLHttpRequest' \
      -H 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36' \
      --cookie "ASP.NET_SessionId=${SESSION_ID}" \
      --data-raw "$payload"
  )

  if [[ "$http_status" =~ ^2[0-9][0-9]$ ]]; then
    # Pretty-print when jq is installed and the response is valid JSON.
    if command -v jq >/dev/null 2>&1 && jq empty "$temp_file" 2>/dev/null; then
      jq '.' "$temp_file" > "$output_file"
      rm -f "$temp_file"
    else
      mv "$temp_file" "$output_file"
    fi

    echo "Saved: ${output_file}"
  else
    error_file="${OUTPUT_DIR}/${bar_id}.error.json"
    mv "$temp_file" "$error_file"

    echo "Request failed with HTTP ${http_status}"
    echo "Response saved in: ${error_file}" >&2
  fi

  echo "----------------------------------------"
  sleep "$DELAY_SECONDS"
done

echo "All requests completed."