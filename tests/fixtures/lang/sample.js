/**
 * Sample JavaScript file used as a parser test fixture.
 *
 * Covers: ES6 static imports (default, named, namespace, side-effect),
 *         CommonJS require, dynamic import, node: protocol, scoped packages.
 */
import fs from 'fs';
import path from 'node:path';
import { EventEmitter } from 'events';

import lodash from 'lodash';
import { debounce } from 'lodash';
import * as R from 'ramda';
import { foo } from '@org/utils';

import './polyfill';
import localHelper from './helpers/local';
import parent from '../shared';

const express = require('express');
const config = require('./config');

async function loadPlugin(name) {
    const mod = await import(name);
    return mod;
}

export default function main() {
    return lodash.identity(42);
}
