uvicorn main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 1200 --log-level info




# Force pull repo steps
## Make sure you’re on the branch you want (e.g. main)
git checkout main

## Fetch latest from remote
git fetch origin

## Reset local branch to be identical to remote
git reset --hard origin/main

## Clean up untracked files & dirs (optional but ensures exact match)
git clean -fd

docker build -t sap-bot .
docker run --rm -p 8000:8000 --env-file /path/to/clean.env -v $(pwd)/reports:/app/reports sap-bot
