# Roadmap

<!-- ÍNDICE ordenado de futuros changes: una línea por entrada + una sub-línea de
     metadatos. Barato de mantener a mano y escaneable de un vistazo.

     El análisis largo de una entrada NO va aquí — va a `sdd/roadmap/<feature>.md`,
     que solo lee `/sdd:new` cuando le llega el turno. Este fichero lo leen TODAS
     las fases, así que se mantiene corto a propósito.

     Quién escribe aquí: `/sdd:new` convierte la siguiente entrada en proposal
     just-in-time, y `/sdd:archive` la marca `[x]` cuando prueba el merge. Nada
     más. El estado en curso (`▶` `✓` `PR` `⛔`) se DERIVA de
     `sdd/changes/<feature>/STATE.md`, no se anota aquí. -->

<!-- METADATOS — sub-línea indentada bajo la entrada, campos separados por ` · `.
     Vocabulario cerrado: `/sdd:doctor` avisa de claves desconocidas (protege de
     erratas tipo `need:`, que si no no harían nada en silencio).

     Aristas del grafo (la otra entrada debe estar cerrada antes que esta):
       needs:          dependencia dura — necesita algo que la otra crea
       completes:      cierra lo que la otra entregó a medias
       informs-from:   la otra es entrada de diseño de esta (típico: un spike)
       inherits-from:  hereda un requisito o medición que la otra aplazó

     Sin arista:
       deferred-until: condición de disparo externa, texto libre. Ponla en su
                       propia sub-línea si contiene ` · `.

     Clasificación:
       size: S | M | L
       kind: feature | fix | spike | infra | tech | adr

     El grafo es un DAG, no un árbol: una entrada puede depender de varias.
     NO uses sangría de lista para expresar jerarquía — una línea indentada que
     empiece por `- [` se parsea como entrada independiente, no como hija.

     Vistas derivadas (nunca se escriben a mano): `/sdd:status` imprime la
     frontera (qué se puede atacar ya, en paralelo), las olas, el camino crítico
     del stage y las entradas sin dependencias. -->

Categorías del proyecto (opcional — define las tuyas): `[FE]` frontend · `[BE]` backend · `[INFRA]` infra · `[TECH]` deuda técnica

## Stage 1 — <el resultado que existe al cerrar este stage>

<!-- Un stage es un FIN a alcanzar ("PMS real en producción"), no una categoría:
     sus entradas son lo que hace falta para llegar a él. Agrupar por categoría
     esconde las cadenas, porque las cadenas cruzan categorías. -->

- [ ] <feature-name> — <una línea de qué es> (fuente: plan.md §N)
      size: S · kind: infra
- [ ] <otra-feature> — <una línea de qué es>
      needs: <feature-name> · size: M · kind: feature

## Stage 2 — <el siguiente resultado>

- [ ] <un-spike> — <medir X antes de diseñar contra supuestos>
      size: S · kind: spike
- [ ] <tercera-feature> — <una línea de qué es>
      needs: <otra-feature> · informs-from: <un-spike> · size: L · kind: feature
- [ ] <aplazada> — <una línea de qué es>
      deferred-until: <la condición externa que la dispara> · size: M · kind: infra
