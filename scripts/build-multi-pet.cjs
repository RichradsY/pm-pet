'use strict';
const fs = require('node:fs');
const path = require('node:path');
const base = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(base, p), 'utf8');
const original = read('prototypes/pm-pet-desktop.html');
const style = original.match(/<style>([\s\S]*?)<\/style>/)[1].replaceAll('#pm-pet-desktop', '#pm-pet-multi');
const owl = original.match(/  <button class="pp-pet"[\s\S]*?  <\/button>/)[0]
  .replace('aria-controls="pm-pet-progress-panel"', 'aria-controls="mp-panel"');
const output = read('prototypes/multi-pet-view.html')
  .replace('/* ORIGINAL_OWL_STYLES */', style)
  .replace('<!-- OWL_TEMPLATE -->', owl)
  .replace('/* MODEL_SOURCE */', read('prototypes/multi-pet-model.js'))
  .replace('/* VIEW_SOURCE */', read('prototypes/multi-pet-view.js'));
fs.writeFileSync(path.join(base, 'prototypes/pm-pet-multi.html'), output);
console.log('Built prototypes/pm-pet-multi.html');
