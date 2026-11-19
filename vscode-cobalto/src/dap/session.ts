// What a debug session knows once it is launched: the options of the proxy
// and the maps that "cobalto debug" left in build/ for the suite.

import { ProgramMap } from './cobol-map';
import { Layout } from './layout';
import { LineMap } from './line-map';

export interface ProxyOptions {
  lldbDapPath: string;
  lldbDapArgs?: string[];
  log?: (s: string) => void;
  /** trace of every message (verbose) */
  trace?: boolean;
  formatValues?: boolean;
  maxFormattedFields?: number;
  /** maximum steps per COBOL statement before giving up */
  maxSteps?: number;
}

export class Session {
  /** C names (b_NNN) to COBOL names, per program */
  maps = new Map<string, ProgramMap>();
  /** generated line to source file and line */
  lineMap?: LineMap;
  /** data layout of each program */
  layout?: Layout;
  suite?: string;
  /** whether the adapter has the readMemory and writeMemory requests
   *  (lldb-dap 18, the one in Ubuntu 24.04, has neither) */
  canReadMemory = false;
  canWriteMemory = false;
  formatValues: boolean;
  readonly maxFormatted: number;
  readonly maxSteps: number;

  constructor(opts: ProxyOptions) {
    this.formatValues = opts.formatValues !== false;
    this.maxFormatted = opts.maxFormattedFields ?? 200;
    this.maxSteps = opts.maxSteps ?? 400;
  }
}
