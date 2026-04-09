/**
 * Sample TypeScript file used as a parser test fixture.
 *
 * Covers: named, default, type-only, and namespace imports;
 *         Node builtins, external packages, local and parent-relative paths;
 *         re-export forms (export * from, export { } from, export * as ns from).
 */
import fs from 'fs';
import { readFile } from 'fs/promises';
import path from 'node:path';

import { Component, OnInit } from '@angular/core';
import type { Observable } from 'rxjs';
import * as _ from 'lodash';

import { AppService } from './app.service';
import { Config } from '../config';

export * from './utils';
export { AppService } from './app.service';
export { default as Config } from '../config';
export * as helpers from './helpers';

export class AppComponent implements OnInit {
    constructor(private svc: AppService) {}

    ngOnInit(): void {
        const p = path.join(__dirname, 'assets');
        console.log(p);
    }
}
