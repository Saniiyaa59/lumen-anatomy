# Attribution

## 3D model

`assets/models/heart.glb` is a modified extract of:

- **Z-Anatomy** — "Z-Anatomy - The libre 3D atlas of anatomy", CC BY-SA 4.0, https://github.com/Z-Anatomy/Models-of-human-anatomy
- which is derived from **BodyParts3D**, © The Database Center for Life Science, licensed under CC Attribution-Share Alike 2.1 Japan.

Changes: heart structures selected, modifiers applied, vessel curves converted to meshes, objects renamed, exported as glTF. The modified model is shared under the same license (CC BY-SA 4.0).

To check before submission: Z-Anatomy notes that a few of its models carry other licenses; confirm in its repository's credits that none of the heart parts do.

`assets/regions/heart/model.glb`, `structures.json` and `centerlines.json` are extracts of the same atlas under the same terms. Changes: heart structures selected, modifiers applied, vessel curves converted to meshes and to sampled centre lines, objects renamed, exported as glTF and JSON.

## Text

`assets/text/z_anatomy_articles.jsonl` holds the description articles stored in the Z-Anatomy file. 2,756 of the 3,675 distinct articles are extracts of English Wikipedia articles, licensed CC BY-SA 4.0; each carries a link to its source article in `source_url`. 902 have no link and are Z-Anatomy's own short definitions. The text is unchanged apart from moving the link out of the body. Any place the app shows this text must show the link with it.

To check before submission: 15 articles link to other sites (for example `ta2viewer.openanatomy.org`); confirm their terms or drop them.

OpenStax *Anatomy and Physiology 2e*, CC BY 4.0 (added in Phase 3, with a link per chunk).
