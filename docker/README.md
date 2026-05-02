# Local infrastructure

Run Redis and Mosquitto without reading Django's `.env` file:

```powershell
docker compose --env-file .docker.env up -d redis mosquitto
```

Check Redis:

```powershell
docker exec dwv2-redis redis-cli ping
```

Check Mosquitto logs:

```powershell
docker logs --tail 20 dwv2-mosquitto
```

Stop services:

```powershell
docker compose --env-file .docker.env down
```
