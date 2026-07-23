#!/bin/bash
# Ежедневный бэкап живого состояния сервера в GitHub (ветка server-backup)
cd /opt/salary-bot || exit 1
export GIT_SSH_COMMAND="ssh -i /root/.ssh/github_backup -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
git add -A
# защита: секреты НЕ коммитим
if git diff --cached --name-only | grep -iqE "(^|/)(\.env|credentials\.json)$"; then
  echo "$(date) SECRETS staged — abort" >> /opt/salary-bot/backup.log; git reset -q; exit 1
fi
if git diff --cached --quiet; then
  echo "$(date) no changes" >> /opt/salary-bot/backup.log; exit 0
fi
git commit -q -m "backup: $(date +%F\ %T)"
git push -q origin server-backup && echo "$(date) pushed OK" >> /opt/salary-bot/backup.log || echo "$(date) push FAILED" >> /opt/salary-bot/backup.log
