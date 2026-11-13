#!/usr/bin/env bash
# Разворачивает лендинг в AWS: стек (S3, CloudFront, функция заявок), код функции, файлы сайта.
# Первый запуск: LEADS_EMAIL=you@example.com infra/landing/deploy.sh
# Повторные запуски адрес не требуют. Сменить адрес — снова передать LEADS_EMAIL.
set -euo pipefail

STACK="${STACK:-satushy-landing}"
REGION="${AWS_REGION:-eu-central-1}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export AWS_PAGER=""

out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo "==> Сборка сайта"
(cd "$ROOT/apps/web" && LANDING_ONLY=1 NEXT_TELEMETRY_DISABLED=1 npx next build >/dev/null)
DIST="$ROOT/apps/web/out"

echo "==> Стек $STACK ($REGION)"
params=()
if ! aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
  : "${LEADS_EMAIL:?Первый запуск: укажите LEADS_EMAIL — адрес для заявок}"
  params=(--parameter-overrides "LeadsEmail=$LEADS_EMAIL" "OriginSecret=$(openssl rand -hex 24)")
elif [ -n "${LEADS_EMAIL:-}" ]; then
  params=(--parameter-overrides "LeadsEmail=$LEADS_EMAIL")
fi
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$ROOT/infra/landing/stack.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  ${params[@]+"${params[@]}"}

echo "==> Код функции заявок"
FN="$(out LeadFunctionName)"
ZIP="$(mktemp -d)/lead.zip"
(cd "$ROOT/apps/landing/lambda" && zip -q -j "$ZIP" handler.py)
aws lambda update-function-code --region "$REGION" --function-name "$FN" \
  --zip-file "fileb://$ZIP" --query LastUpdateStatus --output text >/dev/null
aws lambda wait function-updated --region "$REGION" --function-name "$FN"

echo "==> Файлы сайта"
BUCKET="$(out SiteBucketName)"
# Скрипты, стили и шрифты сборки: в имени хеш, поэтому в кеш на год.
aws s3 sync "$DIST/_next" "s3://$BUCKET/_next" --region "$REGION" --delete --only-show-errors \
  --cache-control "public, max-age=31536000, immutable"
# Страницы — на пять минут, чтобы правки расходились быстро.
# widget.js — скрипт виджета сервиса, на лендинге он не нужен.
aws s3 sync "$DIST" "s3://$BUCKET" --region "$REGION" --delete --only-show-errors \
  --exclude "_next/*" --exclude "widget.js" \
  --cache-control "public, max-age=300"

echo "==> Сброс кеша CloudFront"
aws cloudfront create-invalidation --distribution-id "$(out DistributionId)" --paths "/*" \
  --query Invalidation.Status --output text >/dev/null

echo "Готово: $(out SiteUrl)"
