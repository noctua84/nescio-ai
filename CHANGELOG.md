# Changelog

## [1.5.0](https://github.com/noctua84/nescio-ai/compare/v1.4.0...v1.5.0) (2026-09-04)


### Features

* **crew:** bound qa-guard's write scope and audit it by diff ([2bf6b6d](https://github.com/noctua84/nescio-ai/commit/2bf6b6d6fd470aa5600ae57b04189f697df1a789))
* **crew:** bound qa-guard's write scope and audit it by diff ([caaa3a0](https://github.com/noctua84/nescio-ai/commit/caaa3a079bf7dab18e3321431a1928e9ab42267a))
* **docs:** draw the full 17-agent roster in the crew diagram ([d923f62](https://github.com/noctua84/nescio-ai/commit/d923f62b4591b17160aaa39c19de4dc83486f936))
* **docs:** draw the full 17-agent roster in the crew diagram ([ec21441](https://github.com/noctua84/nescio-ai/commit/ec21441a81d769a98db4c1b2a5162736414ba139))
* **theme:** name the four new crew roles after philosophers ([c79dbac](https://github.com/noctua84/nescio-ai/commit/c79dbaca4850fe3f2743192769ab43b17fbd1ac3))


### Bug Fixes

* [impl] converge a desynced crew tree and pre-flight rename conflicts ([7c1fb80](https://github.com/noctua84/nescio-ai/commit/7c1fb801f342a66d3d28ea149bca6cebc8269f6c))
* [impl] declare the bounded writers' file boundary in their charters ([5f83dfd](https://github.com/noctua84/nescio-ai/commit/5f83dfde4f462729c5e87a79dc800610ebba2905))
* [impl] extract crew constants and fix theme tier corruption ([cfd7285](https://github.com/noctua84/nescio-ai/commit/cfd72851650667c1f5cc8c80dfdc00c482b34bc8))
* [impl] make the write-boundary doc-lint bite, and fix Edit detection ([3c657a0](https://github.com/noctua84/nescio-ai/commit/3c657a05ecddf166038959420f0956716bba580e))
* [impl] rewrite ALL-CAPS crew names when applying the theme ([1e0a5bd](https://github.com/noctua84/nescio-ai/commit/1e0a5bda10e11f6e6f89173c328243e5bab44cae))
* [test] pin the theme properties the round trip cannot see ([6eda19e](https://github.com/noctua84/nescio-ai/commit/6eda19e05ff064a1f7601f238acb3629c53a1d08))
* [test] rebuild the write-policy tests on the shared crew roster ([89e104b](https://github.com/noctua84/nescio-ai/commit/89e104bd0ba2f874729deeed3a5c6940340fa025))
* **agents:** correct the write-access claim in the builder charters ([36d04aa](https://github.com/noctua84/nescio-ai/commit/36d04aab84b9e02f8bb314ba802f205ae5bf902e))
* **agents:** correct the write-access claim in the builder charters ([a2f30bf](https://github.com/noctua84/nescio-ai/commit/a2f30bf1b441e25534866abeee23136cbe9c2486))
* **agents:** correct the writer count after qa-guard left CODE_WRITERS ([4b83487](https://github.com/noctua84/nescio-ai/commit/4b834875536d5b5b0f1792e42c4a79ce3170e771))
* correct README write-permission claim and guard vacuous tests ([63bc4fe](https://github.com/noctua84/nescio-ai/commit/63bc4fe496abe792bb5ae3f3ff54014ce0f16f47))
* **crew:** close the blind spots in the qa-guard CI gate audit ([eef18fa](https://github.com/noctua84/nescio-ai/commit/eef18faaadf8b7947b67e9eb4ff7ec4cc1b2356d))
* **crew:** derive the boundary match mode from the boundary's shape ([ac04470](https://github.com/noctua84/nescio-ai/commit/ac0447045c3d7e6cfe0856e4541b33e45686c6a9))
* **crew:** make the CI gate assertion count staged-aware ([95c1784](https://github.com/noctua84/nescio-ai/commit/95c1784201257e6fa4412cd6151eb2e66286c431))
* **crew:** teach the theme and the tests about the six new agents ([714ea43](https://github.com/noctua84/nescio-ai/commit/714ea4316deb908cc7da634757cd04d78c53b969))
* **docs:** stop gating merges on catalog drift; make the site self-heal ([e3a6bfe](https://github.com/noctua84/nescio-ai/commit/e3a6bfef613a97c95ed7b24df6909c3b45e7cbc5))
* **install:** make hook wiring matcher-aware ([bf5e50a](https://github.com/noctua84/nescio-ai/commit/bf5e50aeaee0c9127fa58657c2f7a4c881cddf1a))
* **install:** make hook wiring matcher-aware ([eb4c46e](https://github.com/noctua84/nescio-ai/commit/eb4c46e0539f1878726cbcbd4641e3d01de7cbb7))
* **readiness:** classify markers before splicing, and refuse when malformed ([ceebae1](https://github.com/noctua84/nescio-ai/commit/ceebae1f7e64e51c17c09378a888ed20329f37ff))
* **readiness:** classify markers before splicing, and refuse when malformed ([ecd9818](https://github.com/noctua84/nescio-ai/commit/ecd981878b297e99124a8f106e38a0e6ca17f917))
* **tests:** reject a revoked write-access declaration ([7cf1b89](https://github.com/noctua84/nescio-ai/commit/7cf1b89798c21bbfcf6f7b43154b4b2e9b8bbdc1))
* verify theme convergence and refuse an ambiguous tree ([3be082c](https://github.com/noctua84/nescio-ai/commit/3be082c447080eaa52ad521d3295194b765f413c))
* **wiki:** stop wiki_index destroying hand-written MEMORY.md content ([b203aa6](https://github.com/noctua84/nescio-ai/commit/b203aa644da8be0294b3a0c9115a61534d7a8743))


### Documentation

* **brand:** drop the crew count from the diagram caption ([fae6510](https://github.com/noctua84/nescio-ai/commit/fae65101ca1954a8ced778ea876bbf65dfabde7f))
* **brand:** re-measure the note-placement comment against the current layout ([d7cfc21](https://github.com/noctua84/nescio-ai/commit/d7cfc214969bb0d0583b101d199e6498c96a7c07))
* **catalog:** regenerate after qa-guard's charter gained a boundary line ([e7387bb](https://github.com/noctua84/nescio-ai/commit/e7387bb8456cdaaac062f3361a8cd91466213a28))
* **catalog:** regenerate agents.md from the pinned routing table ([1fdccd0](https://github.com/noctua84/nescio-ai/commit/1fdccd04f27bcc114008bcbed948f3e0de8e66e4))
* **catalog:** regenerate the agent catalog after [#90](https://github.com/noctua84/nescio-ai/issues/90) ([04bf479](https://github.com/noctua84/nescio-ai/commit/04bf4799448ada1e2561af7a8e4c044b5067c845))
* **ci:** correct the catalog-guard comment's history ([1c7c5c3](https://github.com/noctua84/nescio-ai/commit/1c7c5c33ba0c6de96314fe69d25cb8076eb065c0))
* **contributing:** catalog routing is a courtesy, not a merge gate ([a13460b](https://github.com/noctua84/nescio-ai/commit/a13460bbe83ef8ca2dd82f96a985a32546c3f69b))
* **contributing:** write down what registering an agent requires ([f3b64c3](https://github.com/noctua84/nescio-ai/commit/f3b64c3ab4566533767d6e82dfc25de53c724947))
* document the six new crew members in the README ([c99f24e](https://github.com/noctua84/nescio-ai/commit/c99f24e14188666fd0ab82e94a3d512fe7356e60))
* **plans:** record what was built, not what was proposed ([57b1c88](https://github.com/noctua84/nescio-ai/commit/57b1c885bac037479f529b9d908a91ade9736782))
* **plans:** track the docs-catalog single-roster plan ([5e41a38](https://github.com/noctua84/nescio-ai/commit/5e41a38bcb1d05029533e2ded4e39226300109d0))
* **plans:** track the philosopher-theme plan ([2bb2226](https://github.com/noctua84/nescio-ai/commit/2bb2226c65f641636ec3e65e2f62afea6da93f3f))
* warn about themed checkouts and fix the BuiltSiteTest count ([cab8079](https://github.com/noctua84/nescio-ai/commit/cab8079798a322da41a24c5fb953a7e25cd54c54))

## [1.4.0](https://github.com/noctua84/nescio-ai/compare/v1.3.1...v1.4.0) (2026-08-30)


### Features

* **docs:** fit the diagrams to the column and open them full size ([9ae3904](https://github.com/noctua84/nescio-ai/commit/9ae39043e80e047b62765f92ff263ea3655eb3c7))
* **docs:** fit the diagrams to the column and open them full size ([178c8a0](https://github.com/noctua84/nescio-ai/commit/178c8a006274dfe19f7fc4dbf5be008eaee3911e))
* **harvest:** add a promotion receipt and a stamp rollback tool ([1355202](https://github.com/noctua84/nescio-ai/commit/1355202d670f7b93c337bd36464185e7d2c3f4a0))
* **harvest:** declare the trails a harvest reads up front ([0e09886](https://github.com/noctua84/nescio-ai/commit/0e09886799377af8dd5518cbff4e790db1fe495b))
* **roadmap:** add the fetch layer and network reconciliation checks ([824126d](https://github.com/noctua84/nescio-ai/commit/824126db550a8d1e484e3ef0e704c5fb3c553f27))
* **roadmap:** automatic drift check against open issues and milestones ([#60](https://github.com/noctua84/nescio-ai/issues/60)) ([84f742a](https://github.com/noctua84/nescio-ai/commit/84f742a7b0a476998e3245d707556fe06b20cef3))
* **roadmap:** guard README's roadmap section against issue state ([6348d40](https://github.com/noctua84/nescio-ai/commit/6348d408ee8ead96813a110e465c90f4ea63e355))
* **scripts:** add the roadmap drift checker's parser, offline checks, and CLI ([f18e6d7](https://github.com/noctua84/nescio-ai/commit/f18e6d7b6d54e817c794d07afac475442384b6ab))


### Bug Fixes

* **brand:** rebalance the crew diagram's centre stack ([a180586](https://github.com/noctua84/nescio-ai/commit/a1805867013c5e479be31059e63fcbc9cf0f163d))
* **harvest:** stamp only the trails a harvest declared it read ([7bee607](https://github.com/noctua84/nescio-ai/commit/7bee607a2f3285e8100f88dd05e08055ba097b6b))
* **harvest:** stamp only the trails the harvest declared it read ([26a954d](https://github.com/noctua84/nescio-ai/commit/26a954d44e96d46ca5413dadb6598029ba4a23ee))
* **sync:** compare framework files as text, not bytes ([79efff9](https://github.com/noctua84/nescio-ai/commit/79efff9adebaeb0d63dd5a9c71f097960d8b3c48))
* **sync:** compare framework files as text, not bytes ([d52af12](https://github.com/noctua84/nescio-ai/commit/d52af128cd2aa14943aad43520193d8d36197d7b)), closes [#100](https://github.com/noctua84/nescio-ai/issues/100)


### Documentation

* **case-studies:** add orchestration failure-modes case study ([2beb76e](https://github.com/noctua84/nescio-ai/commit/2beb76e78c552d5d3b31143b4853435b7e1b1242))
* **case-studies:** name the mechanism behind the concurrency failure ([7a06e00](https://github.com/noctua84/nescio-ai/commit/7a06e000a29a7d76ba935f46ad34d4eee3aa0a70))
* **case-studies:** name the mechanism behind the concurrency failure ([9e4bbfd](https://github.com/noctua84/nescio-ai/commit/9e4bbfd186c9fe5167273ee42fab27cf4410e89f))
* **case-studies:** three scope decisions, all correct, none the same rule ([1614eea](https://github.com/noctua84/nescio-ai/commit/1614eea7e70b32aca6230d0782d6fc389e54baea))
* **case-studies:** three scope decisions, all correct, none the same rule ([b6f2e21](https://github.com/noctua84/nescio-ai/commit/b6f2e21fe0ad97128ed262f993a725f7165b70ba))
* **case-studies:** what the crew caught, and what it cost the orchestrator to learn it ([c9aed56](https://github.com/noctua84/nescio-ai/commit/c9aed569319347d7fb212442f4b91c0bb8fcf255))
* **harvest:** rewrite the watermark steps and record ADR 0003 ([7d0562b](https://github.com/noctua84/nescio-ai/commit/7d0562be5d0594b2d350c28b2c11871ea7b896ed))
* **issues:** migrate to issue forms and document what earns a roadmap line ([ca1f546](https://github.com/noctua84/nescio-ai/commit/ca1f546f1e21dabf38cb273bae1fed3fe393bc12))
* **memory:** record ADRs 0001-0002 on frameworks and memory retrieval ([71248b9](https://github.com/noctua84/nescio-ai/commit/71248b94e06b30d52ece457045468dac6ee6a0d0))
* **memory:** record ADRs 0001-0002 on frameworks and memory retrieval ([3a2fa97](https://github.com/noctua84/nescio-ai/commit/3a2fa979d5207e5dc4f53a610478725ef64b6a1e))
* **plans:** track the drift-check plan under .sisyphus/ ([44e66ed](https://github.com/noctua84/nescio-ai/commit/44e66ed93fcac1318891998bf67de1a83403ee0c))
* **roadmap:** document the drift check and the allow-list policy ([288a817](https://github.com/noctua84/nescio-ai/commit/288a817df293bed938f5fd6c737d43d61869eda0))
* **roadmap:** reconcile against current implementation and open issues ([5281661](https://github.com/noctua84/nescio-ai/commit/5281661e1ab12f5e13ae42ccb17e6646e4f3d527))
* **roadmap:** reconcile against current implementation and scope to planned features ([8bc71ac](https://github.com/noctua84/nescio-ai/commit/8bc71ac2dffb78737c7f353322fc6d12e9b17f63))
* **specs:** propose six team workflow patterns from production team use ([e0264dd](https://github.com/noctua84/nescio-ai/commit/e0264ddcc63a4e7697f3c52691e8fbd52b058258))

## [1.3.1](https://github.com/noctua84/nescio-ai/compare/v1.3.0...v1.3.1) (2026-08-26)


### Bug Fixes

* **docs:** restore the homepage navigation rail ([5f87c07](https://github.com/noctua84/nescio-ai/commit/5f87c072b64dd0f0c9b0434d70a57676efb9c5d4))
* **docs:** restore the homepage navigation rail ([28719ac](https://github.com/noctua84/nescio-ai/commit/28719acba3846496d855ba50862bf5a15557bdda))
* **docs:** stop diagrams colliding with the sidebars ([1d5c8ea](https://github.com/noctua84/nescio-ai/commit/1d5c8ea4e1d07e4df17e6b36700c43fd3bcbbfc0))
* **docs:** stop diagrams colliding with the sidebars ([616caa0](https://github.com/noctua84/nescio-ai/commit/616caa0c0f04fd02babc348e74230bba19136a08))


### Documentation

* **design:** mark the docs-site mockup as a point-in-time snapshot ([b7fe192](https://github.com/noctua84/nescio-ai/commit/b7fe1921f0c7ac2d8f2448bfacf243ac2257662f))
* mark the docs-site mockup as a point-in-time snapshot ([55cd5af](https://github.com/noctua84/nescio-ai/commit/55cd5af208ff7b2d781241dc663c8555c245cb57))
* **plans:** fix stale path to the docs-site mockup ([0185452](https://github.com/noctua84/nescio-ai/commit/01854528dfa21af6a4187ed10279dbebac132e37))

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
