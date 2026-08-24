# Changelog

## [1.3.0](https://github.com/noctua84/nescio-ai/compare/v1.2.0...v1.3.0) (2026-08-23)


### Features

* add a dedicated implementer agent and delivery-boundary routing ([d463744](https://github.com/noctua84/nescio-ai/commit/d463744be48753b18622f947fa27802e65ea4bec))
* **agents:** add builder, the crew's dedicated implementer ([517921e](https://github.com/noctua84/nescio-ai/commit/517921e8e5a597c65dcfaebe133cdbbdd7067675))
* **brand:** add brand generator package with shared palette ([a02cc37](https://github.com/noctua84/nescio-ai/commit/a02cc3781e5d3784cade94511581265b5d45a014))
* **brand:** brand package — shared palette, tokenised diagrams, self-hosted fonts ([4365423](https://github.com/noctua84/nescio-ai/commit/43654236ccd575a69985fd43abe67fc875937dfd))
* **brand:** tokenise diagrams, self-host fonts, outline the wordmark ([b865d7e](https://github.com/noctua84/nescio-ai/commit/b865d7e95d0115a514e2e0de3a2016ab31decea1))
* **docs:** build the real site — schemes, catalog, hero, diagrams ([b7bd1ae](https://github.com/noctua84/nescio-ai/commit/b7bd1aefd0198356e39ebbc3e01b190959486a57))
* **docs:** publish the token-usage toolkit, anonymized ([a3f1ed9](https://github.com/noctua84/nescio-ai/commit/a3f1ed925f804f073c8ee817b8210e9efbeee7a5))
* **docs:** the real site — schemes, catalog, hero, inlined diagrams ([82450dd](https://github.com/noctua84/nescio-ai/commit/82450dd26ad4f9d6b86dbd413c6e398ae1645381))
* **orchestrator:** add Delivery Boundary Check to PLAN ([4078caa](https://github.com/noctua84/nescio-ai/commit/4078caa4f0edba09bf36c78af95c116f49499595))
* **orchestrator:** dispatch implementation tasks to builder ([8f461d0](https://github.com/noctua84/nescio-ai/commit/8f461d07e65ee63ef6635058b30e7fcd32780843))
* **theme:** register builder in the philosopher theme as archimedes ([c26cc2b](https://github.com/noctua84/nescio-ai/commit/c26cc2bdbacbc94de2fc2c51905b8580038afc92))


### Bug Fixes

* **agents:** green CI and close the implementer review findings ([6d6e632](https://github.com/noctua84/nescio-ai/commit/6d6e63248ecdca7d4d6a2c100d30268152ac6d8c))
* **docs:** let diagrams break out of the article column ([124d556](https://github.com/noctua84/nescio-ai/commit/124d55643c7a61c8b0b38bcacdfc3e5d0c56497a))
* **docs:** let diagrams break out of the article column ([f19f996](https://github.com/noctua84/nescio-ai/commit/f19f996a4c825f40247c95d16e4a4656b9188294))
* make framework tests theme-aware and independent of memory/ ([668a69e](https://github.com/noctua84/nescio-ai/commit/668a69e391a1c7f736c3fbf28eb76d5d64adf88b))
* **release:** keep uv.lock version in step with pyproject.toml ([e8f0104](https://github.com/noctua84/nescio-ai/commit/e8f01040c9fb30c31915ba22e39563d3ef541573))
* **release:** keep uv.lock version in step with pyproject.toml ([db5a628](https://github.com/noctua84/nescio-ai/commit/db5a628fb05e6da9053595341fc3524fb65c734b))
* **theme:** preserve charter line endings when switching themes ([1c6fba7](https://github.com/noctua84/nescio-ai/commit/1c6fba733577ad43b7bc478196c2877f407000e1)), closes [#82](https://github.com/noctua84/nescio-ai/issues/82)


### Documentation

* **orchestrator:** disambiguate the controller's own re-verification step ([d948e58](https://github.com/noctua84/nescio-ai/commit/d948e58e0c3f79761889cc022fda8bbc535ea022))
* **plans:** correct the test command and account for the generated catalog ([c7e8b71](https://github.com/noctua84/nescio-ai/commit/c7e8b71b4e2cdc231f6a5c8933d29e6555eaf214))
* **plans:** implementation plan for the builder agent and boundary gate ([68f7df3](https://github.com/noctua84/nescio-ai/commit/68f7df307e38a372440c08a1a2015b6a6716d0b4))
* **specs:** design a dedicated implementer agent and delivery-boundary routing ([9b28db3](https://github.com/noctua84/nescio-ai/commit/9b28db3233383e281c77a0b744359a5b6b6ffa15))
* **usage:** read the Aug-13 step change as a plan change, not a regression ([b0c2569](https://github.com/noctua84/nescio-ai/commit/b0c256918b852fdad55c0d23fb59f9020f55764e))

## [1.2.0](https://github.com/noctua84/nescio-ai/compare/v1.1.1...v1.2.0) (2026-08-19)


### Features

* **docs:** add documentation site pipeline and design system ([e30ceae](https://github.com/noctua84/nescio-ai/commit/e30ceae065e23d460acb7806a667507019479d60))
* **docs:** documentation site pipeline and design system ([146ba09](https://github.com/noctua84/nescio-ai/commit/146ba0967d3b970806ccb689c00de1b337b16323))
* **learning-loop:** compute the generated half of readiness.md from the learning trail ([04d39cf](https://github.com/noctua84/nescio-ai/commit/04d39cf0eba91345c0af47e33af4295b97ad0d83))

## [1.1.1](https://github.com/noctua84/nescio-ai/compare/v1.1.0...v1.1.1) (2026-08-18)


### Bug Fixes

* **record_stop:** record repo_root and transcript_path in trail records ([#66](https://github.com/noctua84/nescio-ai/issues/66)) ([5340c3c](https://github.com/noctua84/nescio-ai/commit/5340c3c527988f58b742ab2f72118c387341692c))

## [1.1.0](https://github.com/noctua84/nescio-ai/compare/v1.0.0...v1.1.0) (2026-08-18)


### Features

* **orchestrator:** verify implementer commits landed on the intended branch ([#61](https://github.com/noctua84/nescio-ai/issues/61)) ([da8d14f](https://github.com/noctua84/nescio-ai/commit/da8d14ff75e17cd2a07d170b66e766b3fdab6b39)), closes [#54](https://github.com/noctua84/nescio-ai/issues/54)


### Bug Fixes

* **harvest:** guard console encoding + correct the staging docs ([#56](https://github.com/noctua84/nescio-ai/issues/56)) ([362d381](https://github.com/noctua84/nescio-ai/commit/362d3814fb09d6a015f62c88f32705b78a81b8d8))
* **install:** don't destroy a working symlink on a failed recreate ([#44](https://github.com/noctua84/nescio-ai/issues/44)) ([e3b09d2](https://github.com/noctua84/nescio-ai/commit/e3b09d2e8ab4cd21da0bf917d558d8814a43d6fd))
* **promote:** preserve note content on overwrite + reindex MEMORY.md ([#45](https://github.com/noctua84/nescio-ai/issues/45)) ([2ce5572](https://github.com/noctua84/nescio-ai/commit/2ce5572b0b195a16a6a779a7eaa7d855ea8e7ed4))
* **wiki_lint:** only lint real notes, not operational files ([#46](https://github.com/noctua84/nescio-ai/issues/46)) ([e687208](https://github.com/noctua84/nescio-ai/commit/e68720814d341f0757c5824527698c1c8931d1f6))


### Documentation

* add compatibility badges to README (Python / platform / license / CI) ([#47](https://github.com/noctua84/nescio-ai/issues/47)) ([e397789](https://github.com/noctua84/nescio-ai/commit/e397789722de37f12112409b484836c3e956f00b))
* add ROADMAP.md ([#50](https://github.com/noctua84/nescio-ai/issues/50)) ([9b77306](https://github.com/noctua84/nescio-ai/commit/9b7730660a8f3e66fa7b0b8218db1b95315853b3))
* bring the roadmap and its README summary current ([#57](https://github.com/noctua84/nescio-ai/issues/57)) ([72ba97a](https://github.com/noctua84/nescio-ai/commit/72ba97ada3a9b86bf69b3be0a89bb1dfbe921802))
* settings.json per-part selection — spec + implementation plan (Layer A1) ([#48](https://github.com/noctua84/nescio-ai/issues/48)) ([27b2299](https://github.com/noctua84/nescio-ai/commit/27b229917bf96e0fbd61827f848db0ed9b9eef8b))
* tag [#60](https://github.com/noctua84/nescio-ai/issues/60) with milestone 1.1 ([#62](https://github.com/noctua84/nescio-ai/issues/62)) ([0048bfe](https://github.com/noctua84/nescio-ai/commit/0048bfe7501b7f074f2602c760f3dffd1c937033))
