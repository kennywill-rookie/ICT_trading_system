#!/bin/bash
# ⚡ ML Monitor → kennyserver 배포 스크립트
# 사용법: bash deploy_kenny.sh
#
# 사전 조건:
#   credentials.env에 KENNY_HOST, KENNY_USER, KENNY_PORT 설정
#   kennyserver에 python3, pm2 설치 완료

set -e

# ─── credentials.env에서 서버 정보 읽기 ───
if [ ! -f credentials.env ]; then
    echo "❌ credentials.env 파일이 없습니다"
    exit 1
fi

KENNY_HOST=$(grep KENNY_HOST credentials.env | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'")
KENNY_USER=$(grep KENNY_USER credentials.env | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'")
KENNY_PORT=$(grep KENNY_PORT credentials.env | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'" || echo "22")
KENNY_PORT=${KENNY_PORT:-22}

if [ -z "$KENNY_HOST" ] || [ -z "$KENNY_USER" ]; then
    echo "❌ credentials.env에 KENNY_HOST, KENNY_USER를 설정해 주세요"
    echo "   예시:"
    echo '   KENNY_HOST="192.168.1.100"'
    echo '   KENNY_USER="kenny"'
    echo '   KENNY_PORT="22"'
    exit 1
fi

REMOTE="$KENNY_USER@$KENNY_HOST"
SSH_CMD="ssh -p $KENNY_PORT"
SCP_CMD="scp -P $KENNY_PORT"
REMOTE_DIR="~/trading"

echo "╔══════════════════════════════════════════════╗"
echo "║  ⚡ ML Monitor → kennyserver 배포            ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  서버: $REMOTE (port $KENNY_PORT)"
echo "  경로: $REMOTE_DIR"
echo ""

# ─── Step 1: 원격 디렉토리 생성 ───
echo "📁 Step 1: 원격 디렉토리 생성..."
$SSH_CMD $REMOTE "mkdir -p $REMOTE_DIR"

# ─── Step 2: 파일 전송 ───
echo "📤 Step 2: 파일 전송..."

FILES=(
    "ml_live_monitor.py"
    "ml_data_pipeline.py"
    "ml_train.py"
    "signal_engine.py"
    "ml_fvg_model.pkl"
    "ml_monitor_config.json"
    "ml_fvg_dataset.csv"
    "credentials.env"
    "config.json"
)

for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
        echo "   $f"
        $SCP_CMD "$f" "$REMOTE:$REMOTE_DIR/$f"
    else
        echo "   ⚠️ $f 없음 — 스킵"
    fi
done

# ─── Step 3: PM2 ecosystem 파일 생성 ───
echo "⚙️  Step 3: PM2 ecosystem 파일 생성..."
REMOTE_HOME=$($SSH_CMD $REMOTE "echo \$HOME")
$SSH_CMD $REMOTE "cat > $REMOTE_DIR/ecosystem.config.js << PMEOF
module.exports = {
  apps: [{
    name: 'ml-monitor',
    script: 'ml_live_monitor.py',
    interpreter: 'python3',
    cwd: '${REMOTE_HOME}/trading',
    autorestart: true,
    max_restarts: 10,
    restart_delay: 60000,
    watch: false,
    env: {
      PYTHONUNBUFFERED: '1'
    },
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    error_file: '${REMOTE_HOME}/trading/logs/error.log',
    out_file: '${REMOTE_HOME}/trading/logs/output.log',
    merge_logs: true,
    max_size: '50M',
    retain: 5,
  }]
};
PMEOF"

# ─── Step 4: pip 패키지 설치 ───
echo "📦 Step 4: pip 패키지 설치..."
$SSH_CMD $REMOTE "cd $REMOTE_DIR && pip3 install --user pandas numpy requests xgboost scikit-learn ta yfinance 2>&1 | tail -3"

# ─── Step 5: 로그 디렉토리 생성 ───
$SSH_CMD $REMOTE "mkdir -p $REMOTE_DIR/logs"

# ─── Step 6: 기존 프로세스 정리 + PM2 시작 ───
echo "🚀 Step 6: PM2 시작..."
$SSH_CMD $REMOTE "cd $REMOTE_DIR && pm2 delete ml-monitor 2>/dev/null; pm2 start ecosystem.config.js && pm2 save"

# ─── Step 7: 상태 확인 ───
echo ""
echo "📊 Step 7: 상태 확인..."
$SSH_CMD $REMOTE "pm2 status ml-monitor"

echo ""
echo "═══════════════════════════════════════════════"
echo "✅ 배포 완료!"
echo ""
echo "  유용한 명령어:"
echo "  $SSH_CMD $REMOTE 'pm2 logs ml-monitor'        # 로그 확인"
echo "  $SSH_CMD $REMOTE 'pm2 status'                  # 상태 확인"
echo "  $SSH_CMD $REMOTE 'pm2 restart ml-monitor'      # 재시작"
echo "  $SSH_CMD $REMOTE 'pm2 stop ml-monitor'         # 중지"
echo "  $SSH_CMD $REMOTE 'cat $REMOTE_DIR/ml_monitor_log.json | python3 -m json.tool | tail -50'  # 결과 로그"
echo "═══════════════════════════════════════════════"
