# Service Mesh

## What is a service mesh?

A service mesh is an infrastructure layer that handles security controls, observability, and traffic management for a microservice application.  Generally, a goal of a service mesh is to add this functionality *without the microservices knowing about it*, enabling developers to separate these concerns from their applications.  

Some examples of service meshes include:

* [Istio](https://istio.io) (see [Charmed Istio](./istio.md) for deploying with Juju)
* [Cilium](https://cilium.io/use-cases/service-mesh/)

## Why do I need a service mesh?

Kubernetes facilitates deploying resiliant and scalable microservice applications in multi-tenant environments, but these deployments also have specific operational concerns:

* how do I protect against person-in-the-middle attacks?
* how do I enforce fine-grained access controls so that only applications who need to talk to each other can?
* how do I gain visibility into the traffic flow of an application?

Service meshes address these problems through:
* authentication: strong identity enforcement in service-to-service communication, including mTLS encryption
* [authorization](../explanation/traffic-authorization.md): explicit service-to-service authorization controls
* observability: automatic observability throughout the mesh
