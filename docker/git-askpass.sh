#!/bin/sh
# Git calls this for the username and password when pushing over https.
# It answers from GITHUB_TOKEN, so the token is never written to disk.
case "$1" in
  Username*) echo "x-access-token" ;;
  *) echo "$GITHUB_TOKEN" ;;
esac
