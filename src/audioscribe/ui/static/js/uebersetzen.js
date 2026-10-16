// Statischen Text der Seite uebersetzen, bevor die Ansichten ihn lesen oder ergaenzen - main.js
// importiert dieses Modul zuerst. Danach gibt die Seite sich frei (index.html blendet sie bis dahin aus).

import { uebersetzeDom } from './i18n.js';

try {
  uebersetzeDom();
} finally {
  document.documentElement.classList.add('uebersetzt');
}
