// Browser-safe lossless copies of the original persona artwork. The embedded
// desktop browser on some Windows installs cannot decode the source WebP files,
// which otherwise leaves the live HUD stuck on the previous generic figure.
import aegirPortrait from "../assets/persona/aegir.png"
import anzuPortrait from "../assets/persona/anzu.png"
import bragiPortrait from "../assets/persona/bragi.png"
import eirPortrait from "../assets/persona/eir.png"
import enkiPortrait from "../assets/persona/enki.png"
import heimdallPortrait from "../assets/persona/heimdall.png"
import hermesPortrait from "../assets/persona/hermes.png"
import maiaPortrait from "../assets/persona/maia.png"
import mestorPortrait from "../assets/persona/mestor.png"
import nabuPortrait from "../assets/persona/nabu.png"
import themisPortrait from "../assets/persona/themis.png"
import umiPortrait from "../assets/persona/umi.png"
import velesPortrait from "../assets/persona/veles.png"
import vulcanPortrait from "../assets/persona/vulcan.png"

const PORTRAITS: Record<string, string> = {
  aegir: aegirPortrait,
  anzu: anzuPortrait,
  bragi: bragiPortrait,
  eir: eirPortrait,
  enki: enkiPortrait,
  heimdall: heimdallPortrait,
  hermes: hermesPortrait,
  maia: maiaPortrait,
  mestor: mestorPortrait,
  nabu: nabuPortrait,
  themis: themisPortrait,
  umi: umiPortrait,
  veles: velesPortrait,
  vulcan: vulcanPortrait,
}

export function personaPortraitForId(personaId: string): string {
  return PORTRAITS[personaId] || anzuPortrait
}
