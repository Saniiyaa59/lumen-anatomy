import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

/**
 * Owns the Three.js scene, camera, renderer and controls.
 *
 * Kept outside React on purpose: later phases add picking, highlighting and
 * camera moves here so the action executor (and the dev console) can call
 * them directly, without going through React state.
 */
export class SceneController {
  readonly scene = new THREE.Scene()
  readonly camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100)

  private readonly renderer: THREE.WebGLRenderer
  private readonly controls: OrbitControls
  private readonly resizeObserver: ResizeObserver
  private readonly container: HTMLElement

  constructor(container: HTMLElement) {
    this.container = container

    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    container.appendChild(this.renderer.domElement)

    this.camera.position.set(2, 1.5, 3)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true

    this.scene.background = new THREE.Color(0x101418)
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.2))
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.5)
    keyLight.position.set(3, 4, 5)
    this.scene.add(keyLight)

    // Placeholder until the heart model is loaded in Phase 1.
    const cube = new THREE.Mesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({ color: 0xc0392b, roughness: 0.5 }),
    )
    cube.name = 'placeholder_cube'
    this.scene.add(cube)

    this.resizeObserver = new ResizeObserver(this.resize)
    this.resizeObserver.observe(container)
    this.resize()

    this.renderer.setAnimationLoop(this.tick)
  }

  dispose(): void {
    this.renderer.setAnimationLoop(null)
    this.resizeObserver.disconnect()
    this.controls.dispose()
    this.scene.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        object.geometry.dispose()
        const materials = Array.isArray(object.material) ? object.material : [object.material]
        materials.forEach((material) => material.dispose())
      }
    })
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }

  private readonly tick = () => {
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  private readonly resize = () => {
    const { clientWidth: width, clientHeight: height } = this.container
    if (width === 0 || height === 0) return
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(width, height)
  }
}
