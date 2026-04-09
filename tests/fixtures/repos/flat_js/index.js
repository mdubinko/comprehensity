const { greet } = require('./utils');
const cfg = require('./config');

console.log(greet(cfg.name));
