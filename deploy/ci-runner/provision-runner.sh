#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=runner.env
source "${SCRIPT_DIR}/runner.env"

fail() {
  printf 'runner_provision_error=%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail root_required
[[ "$(uname -m)" == x86_64 ]] || fail unsupported_architecture

source /etc/os-release
[[ "${ID}" == ubuntu && "${VERSION_ID}" == 24.04 ]] || fail unsupported_operating_system
grep -Fxq 'CLASSIFICATION=NON_PRODUCTION' /etc/ci-runner-host-classification \
  || fail host_not_classified_non_production

for command_name in docker dockerd-rootless-setuptool.sh loginctl newuidmap rootlesskit runuser slirp4netns systemctl; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "missing_${command_name}"
done

[[ "${CI_RUNNER_USER}" =~ ^ghr-[a-z0-9-]+$ ]] || fail invalid_runner_user
[[ "${CI_RUNNER_HOME}" == "/srv/ci/users/${CI_RUNNER_USER}" ]] || fail invalid_runner_home
[[ "${CI_RUNNER_DIR}" == /srv/ci/runners/* ]] || fail invalid_runner_directory
[[ "${CI_RUNNER_CACHE}" == /srv/ci/cache/* ]] || fail invalid_cache_directory

if ! id "${CI_RUNNER_USER}" >/dev/null 2>&1; then
  useradd \
    --create-home \
    --home-dir "${CI_RUNNER_HOME}" \
    --shell /bin/bash \
    --comment "${CI_RUNNER_COMMENT//_/ }" \
    "${CI_RUNNER_USER}"
fi
passwd --lock "${CI_RUNNER_USER}" >/dev/null

actual_home="$(getent passwd "${CI_RUNNER_USER}" | cut -d: -f6)"
[[ "${actual_home}" == "${CI_RUNNER_HOME}" ]] || fail unexpected_runner_home

subuid_count="$(awk -F: -v user="${CI_RUNNER_USER}" '$1 == user {sum += $3} END {print sum + 0}' /etc/subuid)"
subgid_count="$(awk -F: -v user="${CI_RUNNER_USER}" '$1 == user {sum += $3} END {print sum + 0}' /etc/subgid)"
(( subuid_count >= 65536 && subgid_count >= 65536 )) || fail subordinate_ids_missing

runner_uid="$(id -u "${CI_RUNNER_USER}")"
runner_gid="$(id -g "${CI_RUNNER_USER}")"

install -d -m 0755 /srv/ci /srv/ci/users /srv/ci/runners /srv/ci/cache
install -d -o "${CI_RUNNER_USER}" -g "${CI_RUNNER_USER}" -m 0750 \
  "${CI_RUNNER_HOME}" \
  "${CI_RUNNER_DIR}" \
  "${CI_RUNNER_CACHE}" \
  "${CI_RUNNER_CACHE}/toolcache"

slice_dir="/etc/systemd/system/user-${runner_uid}.slice.d"
install -d -m 0755 "${slice_dir}"
cat > "${slice_dir}/50-ci-runner-limits.conf" <<EOF
[Slice]
CPUQuota=${CI_DOCKER_CPU_QUOTA}
MemoryHigh=${CI_DOCKER_MEMORY_HIGH}
MemoryMax=${CI_DOCKER_MEMORY_MAX}
TasksMax=${CI_DOCKER_TASKS_MAX}
IOWeight=60
EOF
chmod 0644 "${slice_dir}/50-ci-runner-limits.conf"

loginctl enable-linger "${CI_RUNNER_USER}"
systemctl daemon-reload
systemctl start "user@${runner_uid}.service"

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
if ! run_as_runner env "DOCKER_HOST=${rootless_socket}" docker info >/dev/null 2>&1; then
  run_as_runner dockerd-rootless-setuptool.sh install --force
fi

docker_override_dir="${CI_RUNNER_HOME}/.config/systemd/user/docker.service.d"
install -d -o "${CI_RUNNER_USER}" -g "${CI_RUNNER_USER}" -m 0750 "${docker_override_dir}"
cat > "${docker_override_dir}/50-ci-limits.conf" <<EOF
[Service]
CPUQuota=${CI_DOCKER_CPU_QUOTA}
MemoryHigh=${CI_DOCKER_MEMORY_HIGH}
MemoryMax=${CI_DOCKER_MEMORY_MAX}
TasksMax=${CI_DOCKER_TASKS_MAX}
LimitNOFILE=1048576
EOF
chown "${CI_RUNNER_USER}:${CI_RUNNER_USER}" "${docker_override_dir}/50-ci-limits.conf"
chmod 0640 "${docker_override_dir}/50-ci-limits.conf"

run_as_runner systemctl --user daemon-reload
run_as_runner systemctl --user enable docker.service
run_as_runner systemctl --user restart docker.service

for _ in {1..30}; do
  if run_as_runner env "DOCKER_HOST=${rootless_socket}" docker info >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

security_options="$(run_as_runner env "DOCKER_HOST=${rootless_socket}" docker info --format '{{json .SecurityOptions}}')"
[[ "${security_options}" == *rootless* ]] || fail rootless_docker_not_confirmed

printf 'provision_status=ok\n'
printf 'runner_user=%s uid=%s gid=%s\n' "${CI_RUNNER_USER}" "${runner_uid}" "${runner_gid}"
printf 'rootless_docker=ok\n'
