# GitHub Actions Auto-Deploy Setup

This document explains how to configure the auto-deployment workflow for Jarvis Core on VPS1.

## Required GitHub Secrets

You need to add the following secrets to your GitHub repository:

1. **VPS1_SSH_KEY** - Private SSH key for accessing VPS1 (77.42.40.146)
2. **TELEGRAM_BOT_TOKEN** - Telegram bot token for deployment notifications
3. **TELEGRAM_CHAT_ID** - Telegram chat ID where notifications should be sent

### How to Add Secrets

1. Go to your GitHub repository: https://github.com/UniTy01/Jarvismax-master
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each secret with its respective value

### Getting the SSH Key

On your VPS1 (77.42.40.146), you can use an existing SSH key or generate a new one:

```bash
# Option 1: Use existing key (if available)
cat ~/.ssh/id_rsa  # Copy this entire content to VPS1_SSH_KEY secret

# Option 2: Generate a new key for GitHub Actions
ssh-keygen -t rsa -b 4096 -f ~/.ssh/github_actions_deploy -N ""
cat ~/.ssh/github_actions_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_actions_deploy  # Copy this to VPS1_SSH_KEY secret
```

### Getting Telegram Credentials

If you already have a Telegram bot configured:

1. **TELEGRAM_BOT_TOKEN**: Check your `.env` file on VPS1:
   ```bash
   grep TELEGRAM_BOT_TOKEN /root/Jarvismax-master/.env
   ```

2. **TELEGRAM_CHAT_ID**: 
   - Send a message to your bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Look for the `"chat":{"id":` value (it's a number)

If you don't have a Telegram bot yet:
1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy the bot token (format: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
4. Send a message to your new bot
5. Get your chat ID from getUpdates endpoint

## Workflow Details

The deployment workflow (`deploy.yml`) triggers on every push to the `main` branch and:

1. ✅ Connects to VPS1 (77.42.40.146) via SSH
2. ✅ Pulls the latest code from GitHub
3. ✅ Rebuilds the Docker image (`jarvismax:latest`)
4. ✅ Stops and removes the old container
5. ✅ Starts the new container with proper volumes and networking
6. ✅ Runs comprehensive smoke tests:
   - Verifies container is running
   - Checks logs for critical errors
   - Tests health endpoints
   - Verifies port 8000 is listening
7. ✅ Sends Telegram notifications on success/failure

## Deployment Configuration

The workflow uses these environment variables (configured in deploy.yml):

- **VPS_HOST**: 77.42.40.146
- **VPS_USER**: root
- **DEPLOY_PATH**: /root/Jarvismax-master
- **CONTAINER_NAME**: jarvis_core
- **DOMAIN**: jarvis.jarvismaxapp.co.uk

## Testing the Workflow

After setting up the secrets, test the workflow by pushing a commit:

```bash
cd /root/Jarvismax-master

# Make a small change
echo "# Test deployment - $(date)" >> README.md

# Commit and push
git add README.md
git commit -m "test: trigger auto-deploy workflow"
git push origin main
```

Then check:
- **GitHub Actions tab**: https://github.com/UniTy01/Jarvismax-master/actions
- **Your Telegram**: You should receive a deployment notification
- **VPS1**: Verify the container is running: `docker ps | grep jarvis_core`

## Troubleshooting

### SSH Connection Fails
- Verify the SSH key is correct and has no extra whitespace
- Ensure the VPS1 firewall allows SSH connections from GitHub's IP ranges
- Test manually: `ssh -i ~/.ssh/deploy_key root@77.42.40.146`
- Check authorized_keys permissions: `chmod 600 ~/.ssh/authorized_keys`

### Docker Build Fails
- SSH into VPS1 and check disk space: `df -h`
- Verify Docker is running: `systemctl status docker`
- Check for syntax errors in Dockerfile
- Review build logs in GitHub Actions

### Container Won't Start
- Check Docker logs: `docker logs jarvis_core`
- Verify environment variables in `.env` file
- Ensure required volumes exist: `ls -la /root/jarvismax-data`
- Check port conflicts: `netstat -tuln | grep 8000`

### Telegram Notifications Not Sending
- Verify TELEGRAM_BOT_TOKEN is correct (no extra spaces)
- Verify TELEGRAM_CHAT_ID is a number (not a string)
- Test manually:
  ```bash
  curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
    -d chat_id=<CHAT_ID> \
    -d text="Test notification"
  ```

### Deployment Succeeds but Service Not Working
- Check if the container is healthy: `docker ps`
- Review application logs: `docker logs jarvis_core --tail 100`
- Verify database connections and other dependencies
- Check Caddy/reverse proxy configuration
- Test directly: `curl http://localhost:8000/health`

## Manual Deployment

If you need to deploy manually (bypassing CI/CD):

```bash
ssh root@77.42.40.146
cd /root/Jarvismax-master
git pull origin main
docker build -t jarvismax:latest .
docker stop jarvis_core && docker rm jarvis_core
docker run -d --name jarvis_core --restart unless-stopped \
  -v /root/jarvismax-data:/app/data \
  -v /root/Jarvismax-master/.env:/app/.env:ro \
  --network host \
  jarvismax:latest
docker logs jarvis_core --tail 50
```

## Rollback Procedure

If a deployment breaks production:

```bash
ssh root@77.42.40.146

# Option 1: Revert to previous image
docker stop jarvis_core
docker rm jarvis_core
docker images | grep jarvismax  # Find previous image tag
docker tag jarvismax:<previous_tag> jarvismax:latest
# Then restart container

# Option 2: Rollback code and rebuild
cd /root/Jarvismax-master
git log --oneline -5  # Find previous commit hash
git reset --hard <previous_commit_hash>
docker build -t jarvismax:latest .
docker stop jarvis_core && docker rm jarvis_core
# Then restart container
```
