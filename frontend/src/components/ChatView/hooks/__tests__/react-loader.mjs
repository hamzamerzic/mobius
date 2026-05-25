// Node ESM loader hook that aliases bare `react` imports to the
// local hook shim. Used by the per-hook test files (run via
// `node --loader=./react-loader.mjs --test ...`) so the hooks
// under test can be unit-tested without a full React renderer.
// See react-hook-shim.mjs for the contract.

import { pathToFileURL } from 'node:url'
import { resolve as pathResolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SHIM = pathToFileURL(pathResolve(__dirname, 'react-hook-shim.mjs')).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'react') {
    return { url: SHIM, shortCircuit: true, format: 'module' }
  }
  return nextResolve(specifier, context)
}
