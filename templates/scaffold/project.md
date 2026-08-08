# Project Steering

> Pendiente de generar. Ejecuta `/sdd:init` para rellenar este documento
> analizando el repositorio, o edítalo a mano.

## Overview

<!-- Qué es este proyecto, para quién, en una frase o dos. -->

## Stack

<!-- Lenguajes, frameworks, versiones relevantes, infra. -->

## Commands

<!-- Comandos exactos que el agente debe usar, descubiertos en este proyecto.
     No copies defaults from the toolkit: -->
<!-- build: -->
<!-- test: -->
<!-- lint: -->
<!-- run local: -->

## Worktree bootstrap

isolation: on-conflict

<!-- LÍNEA DE ARRIBA — cuándo se aísla una feature en su propio worktree:

       on-conflict  (defecto) worktree solo cuando el check encuentra evidencia:
                    otra sesión viva, HEAD en la rama de otra feature, o changes
                    en curso de otras features en este clon.
       always       cada feature en su worktree, la primera incluida. El clon
                    principal se queda en la rama por defecto y limpio, así que
                    todas las sesiones arrancan del mismo sitio. Lo pagas en
                    bootstrap: cada worktree arranca con BD vacía, reinstala
                    dependencias y ocupa su propio disco.

     Cualquier otro valor es un error (SDD026): degradaría al defecto en silencio.

     Y debajo, dos cosas distintas, la segunda se olvida siempre (regla 10).

     (1) QUÉ FALTA — lo que git no se lleva y hay que traer:
           - copiar `.env` desde el worktree principal
           - `make setup` / `npm ci` / `uv sync`
         Si no falta nada, dilo explícitamente: un "nada que copiar" escrito vale
         más que una sección ausente, porque la fase siguiente ya tiene la
         respuesta en vez de volver a preguntar.

     (2) QUÉ NO PUEDE HABER DOS VECES — recursos exclusivos de la máquina:
           - puertos publicados (`make up` en el segundo worktree → address in use)
           - nombres fijos de contenedor, un daemon en un socket conocido
           - una BD con nombre fijo, un lockfile, un puerto de debugger
         Un proyecto puede no necesitar copiar NADA y aun así no poder levantar
         dos stacks. El síntoma no se parece a un fichero que falta: es
         "address already in use", o una suite que pasa sola y falla cuando otro
         worktree está arriba.

     Si hay una restricción de exclusividad, escribe la regla operativa concreta
     ("un stack a la vez: `make down` allí antes de `make up` aquí") y, si vale la
     pena arreglarla, que sea una entrada de roadmap con design — toca compose,
     el task runner y quizá CI. Las tres preguntas que lo deciden están en
     `references/isolation.md`.

     Si la verificación falla en un worktree por algo que esta sección no
     menciona, eso ES el hallazgo: se documenta aquí, no se adivina. -->

## Conventions

<!-- Estructura de carpetas, patrones, estilo, cosas que NO hacer. -->

## Context

<!-- Enlaces: repo, CI, tickets, docs externas. MCPs/skills activados y para qué. -->
