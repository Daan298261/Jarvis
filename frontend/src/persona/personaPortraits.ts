import aegirPortrait from "../assets/persona/aegir.webp"
import anzuPortrait from "../assets/persona/anzu.webp"
import bragiPortrait from "../assets/persona/bragi.webp"
import eirPortrait from "../assets/persona/eir.webp"
import enkiPortrait from "../assets/persona/enki.webp"
import heimdallPortrait from "../assets/persona/heimdall.webp"
import hermesPortrait from "../assets/persona/hermes.webp"
import maiaPortrait from "../assets/persona/maia.webp"
import mestorPortrait from "../assets/persona/mestor.webp"
import nabuPortrait from "../assets/persona/nabu.webp"
import themisPortrait from "../assets/persona/themis.webp"
import umiPortrait from "../assets/persona/umi.webp"
import velesPortrait from "../assets/persona/veles.webp"
import vulcanPortrait from "../assets/persona/vulcan.webp"

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
