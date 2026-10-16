// Englische Texte (deutscher Text -> englischer), je Bereich eine Datei. Jede Datei ist
// `export default {JSON};` - ein Test liest sie als JSON (tests/test_i18n.py).
import allgemein from './allgemein.js';
import seite from './seite.js';
import moduleA from './module-a.js';
import moduleB from './module-b.js';

export default { ...allgemein, ...seite, ...moduleA, ...moduleB };
