## Charms
* tailscale-config
    Workloadless charm where the user configures credentials
* tailscale-k8s
  * Deploys and manages the tailscale operator
  * Uses workload pebble containers to deploy the controller (note for AI, when grilling me make sure we look at all objects installed by the upstream operator and make sure we maintain functionality)
* tailscale-beacon-k8s
  * Lives in the user application's model and acts as an entrypoint to the tailnet using the ingress relation. When related, it will deploy the service needed to join the app to the tailnet.
* tailscale-beacon
  * Machine charm that deploys and runs the tailscale snap.

## Relations
* tailscale-config: relation from the tailscale-config charm to tailscale-k8s and tailscale-beacon which distributes credentials.
* ingress: relation between the application charm and the tailscale-beacon-k8s charm.

## Remember to ask for next session
* Adi's dns pod mystery
* We did not finish addressing each object deployed by the upstream helm chart.