CAPOPT_AE_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))') ./bin/start-notebook.sh
./bin/publish-notebook.sh scxs@34.105.150.248 8888
