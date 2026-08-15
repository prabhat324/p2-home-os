# Disaster Recovery

## Recovery order

Restore the platform in dependency order rather than trying to start every service at once.

1. Network and hostname resolution.
2. core-01 storage mounts and NFS/Samba.
3. compute-01 system and `/srv` application data.
4. Jellyfin and media mount.
5. Immich/private photo mount.
6. compute-02 control-plane services.
7. compute-03 secondary worker services.
8. Project Osho autopilot and publishing.
9. Smart-home/voice extras and non-critical applications.

## core-01 failure

Critical state:

- `/mnt/media` and its filesystem;
- NFS/Samba configuration;
- lightweight infrastructure configuration;
- Tailscale/network configuration.

After replacement/rebuild:

```bash
findmnt /mnt/media
df -h /mnt/media
systemctl status nfs-server --no-pager || true
systemctl status smbd --no-pager || true
```

Then validate from compute-01 that the read-only NFS mount returns.

## compute-01 failure

Rebuild order:

1. Ubuntu and network/SSH.
2. Mount/application storage under `/srv`.
3. Docker + NVIDIA runtime and driver.
4. Restore application configuration.
5. Restore Jellyfin/Immich/Ollama/Osho service definitions.
6. Reconnect read-only `/mnt/media` from core-01.
7. Reconnect `/mnt/photos-primary` for Immich.
8. Validate GPU before resuming Osho.

Do not recreate YouTube uploads during recovery until receipt reconciliation is complete.

## compute-02 failure

Production media and existing GPU jobs may continue, but Osho dashboard/controller and Piper TTS are affected. Rebuild lightweight services and restore the Osho control-plane state before allowing new distributed jobs.

## compute-03 failure

Treat compute-03 as expendable worker capacity. The controller should stop assigning jobs to it; persistent job state must remain outside the worker process or be recoverable by the controller.

## Photo recovery

Original private photos are more important than the Immich application database. Preserve the 3 TB primary library and verified backup first. Immich can be rebuilt and re-indexed if necessary.

## Project Osho recovery

Before retrying any `ready_to_upload` or ambiguous job:

```text
1. inspect /srv/osho/youtube/receipts
2. inspect local job state
3. validate known YouTube video ID if present
4. reconcile published state
5. only upload when no durable success evidence exists
```

This prevents duplicate public uploads after a crash.

## Secret recovery

Git does not contain secrets. Recovery plans must separately account for OAuth refresh tokens, API keys, application passwords, Tailscale credentials, and SSH keys.

## Restore verification

A recovery is not complete until clients can actually use the restored service. Verify Jellyfin playback, Immich read access, Home Assistant control, Osho dashboard state, worker health, and a non-public Osho test job before resuming full automation.
