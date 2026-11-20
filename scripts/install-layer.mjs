// Instala las dependencias del layer común para el runtime de Lambda (Linux x86_64, Python 3.12).
// Uso: npm run layer
//
// - PIP_USER=0 anula "install.user=yes" (Python de Microsoft Store lo trae activado y choca con --target).
// - --platform/--python-version descargan wheels para Lambda aunque se ejecute desde Windows o Mac.
import { spawnSync } from 'node:child_process';

const python = process.platform === 'win32' ? 'python' : 'python3';
const args = [
  '-m', 'pip', 'install',
  '-r', 'infra/layers/common/requirements.txt',
  '-t', 'infra/layers/common/python',
  '--upgrade',
  '--platform', 'manylinux2014_x86_64',
  '--python-version', '3.12',
  '--implementation', 'cp',
  '--only-binary=:all:',
];

const result = spawnSync(python, args, {
  stdio: 'inherit',
  env: { ...process.env, PIP_USER: '0' },
});
process.exit(result.status ?? 1);
