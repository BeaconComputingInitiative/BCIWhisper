val releaseStoreFile = System.getenv("BCI_ANDROID_KEYSTORE")
val releaseStorePassword = System.getenv("BCI_ANDROID_KEYSTORE_PASSWORD")
val releaseKeyAlias = System.getenv("BCI_ANDROID_KEY_ALIAS")
val releaseKeyPassword = System.getenv("BCI_ANDROID_KEY_PASSWORD")

val hasReleaseSigning =
    !releaseStoreFile.isNullOrBlank() &&
    !releaseStorePassword.isNullOrBlank() &&
    !releaseKeyAlias.isNullOrBlank() &&
    !releaseKeyPassword.isNullOrBlank()

plugins {
    id("com.android.application")
}

android {
    namespace = "org.beaconcomputinginitiative.bciwhisper"
    compileSdk = 36
    ndkVersion = "25.2.9519653"

    defaultConfig {
        applicationId = "org.beaconcomputinginitiative.bciwhisper"
        minSdk = 28
        targetSdk = 36
        versionCode = 10
        versionName = "6.0-android-alpha10"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        externalNativeBuild {
            cmake {
                arguments += listOf("-DCMAKE_BUILD_TYPE=Release")
            }
        }
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    buildFeatures {
        buildConfig = true
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/whisper/CMakeLists.txt")
            version = "3.22.1"
        }
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.github.wendykierp:JTransforms:3.1")
}
