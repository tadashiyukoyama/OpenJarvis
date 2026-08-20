#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=runner.env
source "${SCRIPT_DIR}/runner.env"
# shellcheck source=versions.env
source "${SCRIPT_DIR}/versions.env"

fail() {
  printf 'runner_verification_error=%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail root_required
grep -Fxq 'CLASSIFICATION=NON_PRODUCTION' /etc/ci-runner-host-classification \
  || fail host_not_classified_non_production

runner_uid="$(id -u "${CI_RUNNER_USER}")"
runner_env=(
  "HOME=${CI_RUNNER_HOME}"
  "USER=${CI_RUNNER_USER}"
  "LOGNAME=${CI_RUNNER_USER}"
  "XDG_RUNTIME_DIR=/run/user/${runner_uid}"
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${runner_uid}/bus"
)

run_as_runner() {
  runuser -u "${CI_RUNNER_USER}" -- env "${runner_env[@]}" "$@"
}

rootless_socket="unix:///run/user/${runner_uid}/docker.sock"
security_options="$(run_as_runner env "DOCKER_HOST=${rootless_socket}" docker info --format '{{json .SecurityOptions}}')"
[[ "${security_options}" == *rootless* ]] || fail rootless_docker_not_confirmed

run_as_runner systemctl --user is-enabled --quiet docker.service || fail docker_service_not_enabled
run_as_runner systemctl --user is-active --quiet docker.service || fail docker_service_not_active
systemctl is-enabled --quiet "${CI_RUNNER_SERVICE}" || fail runner_service_not_enabled
systemctl is-active --quiet "${CI_RUNNER_SERVICE}" || fail runner_service_not_active

runner_version="$(run_as_runner "${CI_RUNNER_DIR}/bin/Runner.Listener" --version)"
[[ "${runner_version}" == "${GITHUB_RUNNER_VERSION}" ]] || fail unexpected_runner_version
[[ -f "${CI_RUNNER_DIR}/.runner" ]] || fail runner_registration_missing
[[ "$(stat -c '%U:%G' "${CI_RUNNER_DIR}")" == "${CI_RUNNER_USER}:${CI_RUNNER_USER}" ]] \
  || fail runner_directory_owner_mismatch

if ss -lntH '( sport = :2375 or sport = :2376 )' | grep -q .; then
  fail public_docker_api_detected
fi

free_gib="$(df --output=avail -BG / | tail -1 | tr -dc '0-9')"
(( free_gib >= CI_MIN_FREE_GIB )) || fail insufficient_free_disk

printf 'verification_status=ok\n'
printf 'classification=non-production\n'
printf 'rootless_docker=ok\n'
printf 'runner_version=%s\n' "${runner_version}"
printf 'runner_service=active\n'
printf 'free_disk_gib=%s\n' "${free_gib}"
printf 'public_docker_api=closed\n'
