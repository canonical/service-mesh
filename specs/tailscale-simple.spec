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

## Requirements
* Make sure we cover the main use cases of Canonical's managed solutions team
* Secure cross cluster communication
* Expose workloads to users on the tailnet
* Provide secure communication channel between parties
* Charms should be written in such a way to make the added workloads detectable in the ACLs
* Make using tailscale easy
* Support headscale as a coordination server
* Charms with an ingress enpoint should join to the tailnet witout additional code changes
* While we will not *block* such deployments, putting the same charm on the tailnet and a service mesh is not a goal
