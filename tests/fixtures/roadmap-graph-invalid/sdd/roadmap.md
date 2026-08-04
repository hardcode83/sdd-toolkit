# Roadmap

## Stage 1 — la cadena de dominio queda cerrada

- [ ] alpha — abre el ciclo
      needs: beta · size: M · kind: feature
- [ ] beta — lo cierra
      needs: alpha · size: M · kind: feature
- [x] gamma — cerrada antes que su dependencia
      needs: delta · size: S · kind: fix
- [ ] delta — la dependencia que sigue abierta
      size: M · kind: feature
- [ ] epsilon — depende de algo que no existe
      needs: no-such-entry · size: S · kind: fix
- [ ] alpha — declarada dos veces
      size: S · kind: fix
